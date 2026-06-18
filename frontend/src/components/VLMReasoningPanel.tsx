'use client';

/**
 * VLM 推理面板 — VLMReasoningPanel
 * 顯示 VLM 完整推理輸出：場景摘要、危險物、可通行區域、航點提示、速度建議、禁止事項
 */

import type { VLMOutput } from '@/types/schemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';

interface VLMReasoningPanelProps {
  vlmOutput: VLMOutput | null;
  isActive: boolean;
}

/* ─── 危險等級顏色對應 ─── */
const severityColors: Record<string, string> = {
  low: 'bg-emerald-900/80 text-emerald-300 border-emerald-700',
  medium: 'bg-amber-900/80 text-amber-300 border-amber-700',
  high: 'bg-orange-900/80 text-orange-300 border-orange-700',
  critical: 'bg-red-900/80 text-red-300 border-red-700 animate-pulse',
};

/* ─── 速度提示顏色對應 ─── */
const speedHintConfig: Record<string, { color: string; label: string }> = {
  stop: { color: 'bg-red-900/80 text-red-300 border-red-700', label: '⏹ 停車' },
  slow: { color: 'bg-amber-900/80 text-amber-300 border-amber-700', label: '🐢 減速' },
  moderate: { color: 'bg-cyan-900/80 text-cyan-300 border-cyan-700', label: '➡ 中速' },
  maintain: { color: 'bg-emerald-900/80 text-emerald-300 border-emerald-700', label: '✓ 維持' },
  accelerate: { color: 'bg-blue-900/80 text-blue-300 border-blue-700', label: '⚡ 加速' },
};

/* ─── 方向 emoji 對應 ─── */
function directionArrow(dir: string): string {
  const map: Record<string, string> = {
    forward: '↑',
    'forward-right': '↗',
    right: '→',
    'backward-right': '↘',
    backward: '↓',
    'backward-left': '↙',
    left: '←',
    'forward-left': '↖',
  };
  return map[dir] ?? '•';
}

/* ─── 信心度進度條顏色 ─── */
function confidenceGradient(c: number): string {
  if (c >= 0.8) return 'bg-emerald-500';
  if (c >= 0.6) return 'bg-cyan-500';
  if (c >= 0.4) return 'bg-amber-500';
  return 'bg-red-500';
}

export function VLMReasoningPanel({ vlmOutput, isActive }: VLMReasoningPanelProps) {
  /* ─── VLM 未啟動狀態 ─── */
  if (!vlmOutput && !isActive) {
    return (
      <Card className="h-full flex flex-col border-border/50 bg-card/80">
        <CardHeader className="pb-2 pt-3 px-3 flex-shrink-0">
          <CardTitle className="text-xs font-medium uppercase tracking-widest text-muted-foreground flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-600" />
            VLM 推理
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-2">
            <div className="w-10 h-10 rounded-full bg-zinc-800 mx-auto flex items-center justify-center">
              <span className="text-zinc-500 text-lg">⊘</span>
            </div>
            <p className="text-sm text-muted-foreground">VLM 未啟動</p>
            <p className="text-[10px] text-muted-foreground/60">
              等待觸發條件滿足
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  /* ─── VLM 啟動但尚無輸出（推理中） ─── */
  if (!vlmOutput && isActive) {
    return (
      <Card className="h-full flex flex-col border-border/50 bg-card/80">
        <CardHeader className="pb-2 pt-3 px-3 flex-shrink-0">
          <CardTitle className="text-xs font-medium uppercase tracking-widest text-muted-foreground flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
            VLM 推理
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3">
            <div className="w-12 h-12 rounded-full border-2 border-cyan-500/30 border-t-cyan-500 animate-spin mx-auto" />
            <p className="text-sm text-cyan-400 animate-pulse">
              VLM 推理進行中...
            </p>
            <p className="text-[10px] text-muted-foreground/60">
              分析場景中，請稍候
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  /* ─── 有 VLM 輸出：完整顯示 ─── */
  const output = vlmOutput!;
  const speedCfg = speedHintConfig[output.speed_hint] ?? speedHintConfig.maintain;

  return (
    <Card className="h-full flex flex-col border-border/50 bg-card/80">
      <CardHeader className="pb-2 pt-3 px-3 flex-shrink-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-medium uppercase tracking-widest text-muted-foreground flex items-center gap-2">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isActive ? 'bg-cyan-500 animate-pulse' : 'bg-emerald-500'
              }`}
            />
            VLM 推理
          </CardTitle>
          {/* 整體信心度 */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground">Confidence</span>
            <div className="w-16 h-1.5 bg-muted/30 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${confidenceGradient(output.confidence)}`}
                style={{ width: `${output.confidence * 100}%` }}
              />
            </div>
            <span className="font-mono text-[10px] tabular-nums text-foreground">
              {(output.confidence * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex-1 px-3 pb-3 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="space-y-3">
            {/* ─── 場景摘要 ─── */}
            <div className="bg-cyan-950/20 border-l-2 border-cyan-600 pl-3 pr-2 py-2 rounded-r">
              <p className="text-[12px] leading-relaxed text-foreground/90">
                {output.scene_summary}
              </p>
            </div>

            {/* ─── 速度建議 ─── */}
            <div className="flex items-center gap-2">
              <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Speed Hint
              </label>
              <Badge className={`text-xs font-semibold border ${speedCfg.color}`}>
                {speedCfg.label}
              </Badge>
            </div>

            <Separator className="opacity-30" />

            {/* ─── 危險物件 ─── */}
            <div>
              <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Hazards ({output.hazards.length})
              </label>
              <div className="mt-1 space-y-1.5">
                {output.hazards.map((hazard, i) => (
                  <div
                    key={i}
                    className="bg-muted/15 rounded px-2 py-1.5 space-y-0.5"
                  >
                    <div className="flex items-center gap-2">
                      <Badge
                        className={`text-[9px] font-mono border ${severityColors[hazard.severity]}`}
                      >
                        {hazard.severity.toUpperCase()}
                      </Badge>
                      <span className="text-[11px] font-medium">
                        {hazard.label}
                      </span>
                    </div>
                    <p className="text-[10px] text-muted-foreground leading-relaxed">
                      {hazard.description}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <Separator className="opacity-30" />

            {/* ─── 可通行區域 ─── */}
            <div>
              <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Navigable Regions ({output.navigable_regions.length})
              </label>
              <div className="mt-1 space-y-1">
                {output.navigable_regions.map((region) => (
                  <div
                    key={region.region_id}
                    className="flex items-center gap-2 bg-muted/15 rounded px-2 py-1"
                  >
                    <span className="text-base w-5 text-center">
                      {directionArrow(region.direction)}
                    </span>
                    <span className="text-[11px] flex-1 truncate">
                      {region.description}
                    </span>
                    <div className="w-14 h-1.5 bg-muted/30 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${confidenceGradient(region.confidence)}`}
                        style={{ width: `${region.confidence * 100}%` }}
                      />
                    </div>
                    <span className="font-mono text-[10px] tabular-nums w-8 text-right">
                      {(region.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <Separator className="opacity-30" />

            {/* ─── 航點提示 ─── */}
            {output.waypoint_hints.length > 0 && (
              <div>
                <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Waypoint Hints
                </label>
                <div className="mt-1 space-y-1">
                  {output.waypoint_hints.map((hint, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-2 bg-muted/15 rounded px-2 py-1"
                    >
                      <span className="text-base mt-0.5">
                        {directionArrow(hint.direction)}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px]">{hint.description}</p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="font-mono text-[9px] text-muted-foreground tabular-nums">
                            {hint.distance_m.toFixed(1)}m
                          </span>
                          <span className="font-mono text-[9px] text-muted-foreground tabular-nums">
                            conf: {(hint.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <Separator className="opacity-30" />

            {/* ─── 禁止事項 ─── */}
            {output.must_not_do.length > 0 && (
              <div>
                <label className="text-[10px] uppercase tracking-wider text-red-400/80">
                  ⚠️ Must Not Do
                </label>
                <div className="mt-1 space-y-0.5">
                  {output.must_not_do.map((item, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-1.5 text-[11px] text-red-300/80 bg-red-950/20 rounded px-2 py-1"
                    >
                      <span className="flex-shrink-0">⚠️</span>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
