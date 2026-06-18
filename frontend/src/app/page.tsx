'use client';

/**
 * MA-VLNA 主儀表板頁面
 * 研究級即時監控面板 — 包含 5 個核心面板
 * 每 2 秒自動從後端 API 拉取最新資料，後端不可用時回退至模擬資料
 */

import { useState, useEffect, useCallback } from 'react';

/* ─── 面板元件 ─── */
import { StatusPanel } from '@/components/StatusPanel';
import { VisualPanel } from '@/components/VisualPanel';
import { VLMReasoningPanel } from '@/components/VLMReasoningPanel';
import { SceneMemoryPanel } from '@/components/SceneMemoryPanel';
import { ReplayLogsPanel } from '@/components/ReplayLogsPanel';

/* ─── 型別 ─── */
import type {
  VehicleStatus,
  SceneLog,
  SceneMemoryEntry,
  TelemetryEntry,
  PlannerAction,
} from '@/types/schemas';

/* ─── API 與模擬資料 ─── */
import {
  fetchVehicleStatus,
  fetchScenes,
  fetchMemoryTopK,
  fetchTelemetryRecent,
  fetchPlannerState,
} from '@/lib/api';

import {
  mockVehicleStatus,
  mockSceneLogs,
  mockSceneMemories,
  mockTelemetryEntries,
  mockPlannerAction,
} from '@/lib/mock-data';

/* ─── 連線狀態類型 ─── */
type ConnectionState = 'connected' | 'disconnected' | 'connecting';

export default function DashboardPage() {
  /* ─── 面板資料狀態 ─── */
  const [vehicleStatus, setVehicleStatus] = useState<VehicleStatus>(mockVehicleStatus);
  const [currentScene, setCurrentScene] = useState<SceneLog | null>(mockSceneLogs[0]);
  const [plannerAction, setPlannerAction] = useState<PlannerAction | null>(mockPlannerAction);
  const [sceneMemories, setSceneMemories] = useState<SceneMemoryEntry[]>(mockSceneMemories);
  const [telemetryEvents, setTelemetryEvents] = useState<TelemetryEntry[]>(mockTelemetryEntries);
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  /* ─── 資料拉取函式 ─── */
  const refreshData = useCallback(async () => {
    try {
      const [statusRes, scenesRes, memoryRes, telemetryRes, plannerRes] =
        await Promise.allSettled([
          fetchVehicleStatus(),
          fetchScenes(5),
          fetchMemoryTopK(currentScene?.scene_id ?? 'scene-20260605-0421', 5),
          fetchTelemetryRecent(20),
          fetchPlannerState(),
        ]);

      // 車輛狀態
      if (statusRes.status === 'fulfilled' && statusRes.value.data) {
        setVehicleStatus(statusRes.value.data);
      }

      // 最新場景日誌
      if (scenesRes.status === 'fulfilled' && scenesRes.value.data) {
        const scenes = scenesRes.value.data;
        if (scenes.length > 0) setCurrentScene(scenes[0]);
      }

      // 場景記憶
      if (memoryRes.status === 'fulfilled' && memoryRes.value.data) {
        setSceneMemories(memoryRes.value.data);
      }

      // 遙測日誌
      if (telemetryRes.status === 'fulfilled' && telemetryRes.value.data) {
        setTelemetryEvents(telemetryRes.value.data);
      }

      // 規劃器動作
      if (plannerRes.status === 'fulfilled' && plannerRes.value.data) {
        setPlannerAction(plannerRes.value.data);
      }

      setConnectionState('connected');
      setLastUpdate(new Date());
    } catch {
      setConnectionState('disconnected');
    }
  }, [currentScene?.scene_id]);

  /* ─── 每 2 秒自動刷新 ─── */
  useEffect(() => {
    refreshData();
    const interval = setInterval(refreshData, 2000);
    return () => clearInterval(interval);
  }, [refreshData]);

  /* ─── 連線狀態指示器顏色 ─── */
  const connectionColors: Record<ConnectionState, string> = {
    connected: 'bg-emerald-500',
    disconnected: 'bg-red-500',
    connecting: 'bg-amber-500 animate-pulse',
  };

  const connectionLabels: Record<ConnectionState, string> = {
    connected: '已連線',
    disconnected: '模擬模式',
    connecting: '連線中...',
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* ═══ 頂部導航列 ═══ */}
      <header className="flex-shrink-0 border-b border-border bg-card/50 backdrop-blur-sm px-4 py-2">
        <div className="flex items-center justify-between">
          {/* 左側：系統標題與車輛 ID */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
              <h1 className="text-base font-semibold tracking-tight">
                MA-VLNA
              </h1>
              <span className="text-xs text-muted-foreground">Dashboard</span>
            </div>
            <div className="h-4 w-px bg-border" />
            <span className="font-mono text-xs text-cyan-400 bg-cyan-950/30 px-2 py-0.5 rounded">
              {vehicleStatus.vehicle_id}
            </span>
          </div>

          {/* 右側：連線狀態與時間 */}
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <div className={`w-1.5 h-1.5 rounded-full ${connectionColors[connectionState]}`} />
              <span>{connectionLabels[connectionState]}</span>
            </div>
            <span className="font-mono text-[10px]">
              {lastUpdate.toLocaleTimeString('zh-TW', { hour12: false })}
            </span>
          </div>
        </div>
      </header>

      {/* ═══ 主面板網格 ═══ */}
      <main className="flex-1 overflow-hidden p-2 gap-2 grid grid-cols-[320px_1fr_360px] grid-rows-[1fr_1fr]">
        {/* 左欄：狀態面板（跨兩列高） */}
        <div className="row-span-2 overflow-hidden">
          <StatusPanel status={vehicleStatus} />
        </div>

        {/* 中欄上：視覺感知面板 */}
        <div className="overflow-hidden">
          <VisualPanel
            sceneLog={currentScene}
            plannerAction={plannerAction}
          />
        </div>

        {/* 右欄上：場景記憶面板 */}
        <div className="overflow-hidden">
          <SceneMemoryPanel memories={sceneMemories} />
        </div>

        {/* 中欄下：VLM 推理面板 */}
        <div className="overflow-hidden">
          <VLMReasoningPanel
            vlmOutput={currentScene?.vlm_output ?? null}
            isActive={vehicleStatus.vlm_active}
          />
        </div>

        {/* 右欄下：回放日誌面板 */}
        <div className="overflow-hidden">
          <ReplayLogsPanel events={telemetryEvents} />
        </div>
      </main>
    </div>
  );
}
