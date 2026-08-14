'use client';

/**
 * 狀態面板 — StatusPanel
 * 顯示車輛即時狀態：ID、規劃器狀態、速度、觸發原因、VLM 啟用指示、動作、安全模式
 */

import type { VehicleStatus, PlannerState } from '@/types/schemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';

interface StatusPanelProps {
  status: VehicleStatus;
}

/* ─── 規劃器狀態顏色對應 ─── */
const plannerStateColors: Record<PlannerState, string> = {
  idle: 'bg-zinc-600 text-zinc-200',
  navigating: 'bg-emerald-900/80 text-emerald-300 border border-emerald-700',
  vlm_reasoning: 'bg-cyan-900/80 text-cyan-300 border border-cyan-700 animate-pulse',
  executing_plan: 'bg-blue-900/80 text-blue-300 border border-blue-700',
  safe_stop: 'bg-red-900/80 text-red-300 border border-red-700',
  awaiting_review: 'bg-amber-900/80 text-amber-300 border border-amber-700 animate-pulse',
  replaying_memory: 'bg-purple-900/80 text-purple-300 border border-purple-700',
};

const plannerStateLabels: Record<PlannerState, string> = {
  idle: '閒置',
  navigating: '導航中',
  vlm_reasoning: 'VLM 推理中',
  executing_plan: '執行計畫',
  safe_stop: '安全停車',
  awaiting_review: '等待審核',
  replaying_memory: '記憶回放',
};

export function StatusPanel({ status }: StatusPanelProps) {
  return (
    <Card className="h-full flex flex-col border-border/50 bg-card/80">
      <CardHeader className="pb-2 pt-3 px-3 flex-shrink-0">
        <CardTitle className="text-xs font-medium uppercase tracking-widest text-muted-foreground flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-500" />
          車輛狀態
        </CardTitle>
      </CardHeader>

      <CardContent className="flex-1 px-3 pb-3 space-y-3 overflow-auto">
        {/* ─── 安全模式警告 ─── */}
        {status.safe_mode && (
          <div className="rounded-md bg-red-950/60 border border-red-800 px-3 py-2 text-xs text-red-300 flex items-center gap-2">
            <span className="text-base">🚨</span>
            <span className="font-semibold">安全模式啟動</span>
          </div>
        )}

        {/* ─── 車輛 ID ─── */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Vehicle ID
          </label>
          <p className="font-mono text-sm text-foreground mt-0.5">
            {status.vehicle_id}
          </p>
        </div>

        <Separator className="opacity-30" />

        {/* ─── 規劃器狀態 ─── */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Planner State
          </label>
          <div className="mt-1">
            <Badge
              className={`text-[10px] font-mono ${plannerStateColors[status.planner_state]}`}
            >
              {plannerStateLabels[status.planner_state]}
            </Badge>
          </div>
        </div>

        <Separator className="opacity-30" />

        {/* ─── 即時速度（大數字顯示） ─── */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Speed
          </label>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="font-mono text-3xl font-bold text-foreground tabular-nums">
              {status.current_speed.toFixed(1)}
            </span>
            <span className="text-xs text-muted-foreground">m/s</span>
          </div>
        </div>

        <Separator className="opacity-30" />

        {/* ─── VLM 啟用指示器 ─── */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            VLM Status
          </label>
          <div className="flex items-center gap-2 mt-1">
            <div
              className={`w-2.5 h-2.5 rounded-full ${
                status.vlm_active
                  ? 'bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.6)] animate-pulse'
                  : 'bg-zinc-600'
              }`}
            />
            <span
              className={`text-xs font-mono ${
                status.vlm_active ? 'text-cyan-400' : 'text-muted-foreground'
              }`}
            >
              {status.vlm_active ? 'ACTIVE' : 'IDLE'}
            </span>
          </div>
        </div>

        <Separator className="opacity-30" />

        {/* ─── 目前動作 ─── */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Current Action
          </label>
          <div className="mt-1">
            <Badge variant="secondary" className="text-[10px] font-mono">
              {status.current_action}
            </Badge>
          </div>
        </div>

        <Separator className="opacity-30" />

        {/* ─── 觸發原因 ─── */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Last Trigger
          </label>
          <p className="font-mono text-xs text-amber-400/90 mt-0.5">
            {status.last_trigger_reason}
          </p>
        </div>

        <Separator className="opacity-30" />

        {/* ─── 位置與方向 ─── */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Position
          </label>
          <div className="grid grid-cols-3 gap-1 mt-1">
            {(['x', 'y', 'z'] as const).map((axis) => {
              const key = `position_${axis}` as keyof VehicleStatus;
              return (
                <div key={axis} className="bg-muted/30 rounded px-1.5 py-1 text-center">
                  <span className="text-[9px] text-muted-foreground uppercase">{axis}</span>
                  <p className="font-mono text-[11px] tabular-nums">
                    {(status[key] as number).toFixed(2)}
                  </p>
                </div>
              );
            })}
          </div>
        </div>

        {/* ─── 航向 ─── */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Heading
          </label>
          <p className="font-mono text-sm tabular-nums mt-0.5">
            {status.heading_deg.toFixed(1)}°
          </p>
        </div>

        <Separator className="opacity-30" />

        {/* ─── 更新時間 ─── */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Updated
          </label>
          <p className="font-mono text-[10px] text-muted-foreground mt-0.5">
            {new Date(status.updated_at).toLocaleTimeString('zh-TW', { hour12: false })}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
