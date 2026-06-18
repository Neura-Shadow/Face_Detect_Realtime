"""
Phase 11B Real CARLA Server Runtime Smoke Test.

此腳本是 Phase 11B 的真實 CARLA server gate，和 fake runtime gate 分開：

1. 檢查本機 Python 是否安裝 `carla` package。
2. 檢查指定 host/port 是否可建立 TCP 連線。
3. 若前提成立，使用真實 `CarlaClosedLoopAgent` 跑最小步數閉環。
4. 若前提不成立，預設輸出 skipped；加上 `--require-server` 時改為 failed exit。

驗證成功代表：
  "Phase 11B Real CARLA Server Runtime Smoke Pass — setup/tick/control/cleanup verified"

注意：此腳本不追求 CARLA Leaderboard，也不驗證自駕策略品質；它只驗證 MA-VLNA
能實際接上 CARLA server、取得 RGB frame、執行 planner action 到 VehicleControl，
並乾淨釋放 actors。
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import importlib.util
import logging
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.CARLA_Closed_Loop_Agent import CarlaClosedLoopAgent
from workers.core.config import AgentConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("Phase11BRealCarlaSmoke")


@dataclass(frozen=True)
class PreflightResult:
    """Phase 11B 真實 CARLA smoke test 的前置檢查結果。"""

    has_carla_package: bool
    tcp_reachable: bool
    host: str
    port: int
    reasons: list[str]

    @property
    def ready(self) -> bool:
        return self.has_carla_package and self.tcp_reachable

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "ready"


def _carla_package_available() -> bool:
    """檢查目前 Python 環境是否可匯入 CARLA API。"""
    return importlib.util.find_spec("carla") is not None


def _tcp_reachable(host: str, port: int, timeout_sec: float) -> bool:
    """以短 timeout 檢查 CARLA server RPC port 是否可連線。"""
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError as exc:
        logger.info("CARLA TCP preflight failed: %s:%d (%s)", host, port, exc)
        return False


def _run_preflight(host: str, port: int, timeout_sec: float) -> PreflightResult:
    reasons: list[str] = []
    has_carla_package = _carla_package_available()
    if not has_carla_package:
        reasons.append("carla Python package not installed")

    tcp_reachable = _tcp_reachable(host, port, timeout_sec)
    if not tcp_reachable:
        reasons.append(f"CARLA server TCP endpoint unreachable at {host}:{port}")

    result = PreflightResult(
        has_carla_package=has_carla_package,
        tcp_reachable=tcp_reachable,
        host=host,
        port=port,
        reasons=reasons,
    )
    logger.info(
        "Phase 11B preflight: carla_package=%s, tcp_reachable=%s, target=%s:%d",
        result.has_carla_package,
        result.tcp_reachable,
        result.host,
        result.port,
    )
    return result


def _build_smoke_config(args: argparse.Namespace) -> AgentConfig:
    """
    建立 Phase 11B 專用設定。

    預設關閉 Supabase 寫入，避免真實 CARLA smoke test 被雲端狀態阻塞；
    若需要把 telemetry 寫回 Supabase，可用 `--publish-telemetry`。
    """
    config = AgentConfig.load()
    carla_cfg = dataclasses.replace(
        config.carla,
        host=args.host,
        port=args.port,
        timeout_sec=args.timeout_sec,
        town=args.town,
        spawn_point_index=args.spawn_point_index,
        synchronous_mode=not args.async_world,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
    )
    perception_cfg = dataclasses.replace(
        config.perception,
        backend=args.perception_backend,
        model_name=args.perception_model,
    )
    vlm_cfg = dataclasses.replace(
        config.vlm,
        provider=args.vlm_provider,
        timeout_sec=min(config.vlm.timeout_sec, 5.0),
        confidence_threshold=0.4,
    )
    trigger_cfg = dataclasses.replace(
        config.trigger,
        cooldown_sec=0.0 if args.enable_vlm else config.trigger.cooldown_sec,
        force_interval_frames=args.force_vlm_every,
    )
    telemetry_cfg = dataclasses.replace(
        config.telemetry,
        publish_interval_sec=0.1,
        batch_size=4,
    )
    supabase_cfg = config.supabase
    if not args.publish_telemetry:
        supabase_cfg = dataclasses.replace(config.supabase, url="", key="")

    return dataclasses.replace(
        config,
        agent_id="phase11b-real-carla-smoke",
        mode="carla",
        main_loop_hz=args.loop_hz,
        carla=carla_cfg,
        perception=perception_cfg,
        vlm=vlm_cfg,
        trigger=trigger_cfg,
        telemetry=telemetry_cfg,
        supabase=supabase_cfg,
    )


async def _run_real_carla_smoke(args: argparse.Namespace) -> None:
    config = _build_smoke_config(args)
    agent = CarlaClosedLoopAgent(config=config, enable_vlm=args.enable_vlm)
    await agent.run(max_steps=args.steps)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 11B real CARLA server smoke test")
    parser.add_argument("--host", default="127.0.0.1", help="CARLA server host")
    parser.add_argument("--port", type=int, default=2000, help="CARLA server RPC port")
    parser.add_argument("--timeout-sec", type=float, default=5.0, help="CARLA client/preflight timeout")
    parser.add_argument("--town", default="", help="CARLA town/map；留空代表使用目前 world")
    parser.add_argument("--spawn-point-index", type=int, default=0)
    parser.add_argument("--steps", type=int, default=5, help="真實 CARLA closed-loop tick 數")
    parser.add_argument("--loop-hz", type=int, default=20)
    parser.add_argument("--camera-width", type=int, default=320)
    parser.add_argument("--camera-height", type=int, default=180)
    parser.add_argument("--async-world", action="store_true", help="停用 CARLA synchronous_mode")
    parser.add_argument("--enable-vlm", action="store_true", help="允許 Phase 11B 觸發 VLM path")
    parser.add_argument("--force-vlm-every", type=int, default=0)
    parser.add_argument("--vlm-provider", default="local_stub", choices=["local_stub", "openai_compatible", "gemma"])
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "rtdetr"])
    parser.add_argument("--perception-model", default="dummy")
    parser.add_argument("--publish-telemetry", action="store_true", help="使用 .env Supabase 設定寫入 telemetry")
    parser.add_argument("--preflight-only", action="store_true", help="只檢查 carla package 與 TCP endpoint")
    parser.add_argument("--require-server", action="store_true", help="前提不成立時以 exit 1 回報")
    return parser


def _skip_or_fail(preflight: PreflightResult, require_server: bool) -> int:
    message = f"phase11b real carla smoke skipped: {preflight.reason_text}"
    if require_server:
        logger.error(message)
        print(message)
        return 1
    logger.warning(message)
    print(message)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    preflight = _run_preflight(args.host, args.port, args.timeout_sec)
    if args.preflight_only:
        if preflight.ready:
            print("phase11b real carla preflight passed")
            return 0
        return _skip_or_fail(preflight, args.require_server)

    if not preflight.ready:
        return _skip_or_fail(preflight, args.require_server)

    try:
        asyncio.run(_run_real_carla_smoke(args))
    except Exception as exc:
        logger.exception("Phase 11B real CARLA smoke failed")
        print(f"phase11b real carla smoke failed: {exc}")
        return 1

    print("phase11b real carla smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
