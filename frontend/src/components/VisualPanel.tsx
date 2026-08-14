'use client';

/**
 * 視覺感知面板 — VisualPanel
 * 顯示攝影機畫面、偵測物件列表、追蹤摘要、可行駛空間、車道狀態、航點
 */

import type { SceneLog, PlannerAction } from '@/types/schemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';

interface VisualPanelProps {
  sceneLog: SceneLog | null;
  plannerAction: PlannerAction | null;
}

/* ─── 信心度等級顏色 ─── */
function confidenceColor(c: number): string {
  if (c >= 0.9) return 'bg-emerald-500';
  if (c >= 0.7) return 'bg-cyan-500';
  if (c >= 0.5) return 'bg-amber-500';
  return 'bg-red-500';
}

/* ─── 追蹤狀態顏色 ─── */
function trackStatusColor(status: string): string {
  switch (status) {
    case 'active': return 'text-emerald-400';
    case 'tentative': return 'text-amber-400';
    case 'lost': return 'text-red-400';
    default: return 'text-muted-foreground';
  }
}

export function VisualPanel({ sceneLog, plannerAction }: VisualPanelProps) {
  const detections = sceneLog?.detections ?? [];
  const tracks = sceneLog?.tracks ?? [];

  return (
    <Card className="h-full flex flex-col border-border/50 bg-card/80">
      <CardHeader className="pb-2 pt-3 px-3 flex-shrink-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-medium uppercase tracking-widest text-muted-foreground flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            視覺感知
          </CardTitle>
          {sceneLog && (
            <span className="font-mono text-[10px] text-muted-foreground">
              {sceneLog.scene_id}
            </span>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex-1 px-3 pb-3 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="space-y-3">
            {/* ─── 攝影機畫面 / 佔位圖 ─── */}
            <div className="relative aspect-video w-full rounded-md overflow-hidden bg-zinc-900 border border-border/30">
              {sceneLog?.frame_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={sceneLog.frame_url}
                  alt="Camera frame"
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    // 圖片載入失敗時隱藏，顯示佔位背景
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              ) : null}
              {/* 佔位網格圖案 */}
              <div className="absolute inset-0 flex items-center justify-center"
                style={{
                  backgroundImage:
                    'linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)',
                  backgroundSize: '24px 24px',
                }}
              >
                {!sceneLog?.frame_url && (
                  <span className="text-xs text-muted-foreground/50">No Frame Available</span>
                )}
              </div>

              {/* 偵測計數 Badge */}
              {detections.length > 0 && (
                <div className="absolute top-2 right-2">
                  <Badge className="bg-cyan-900/80 text-cyan-300 border border-cyan-700 text-[10px]">
                    {detections.length} detections
                  </Badge>
                </div>
              )}
            </div>

            {/* ─── 車道狀態 ─── */}
            {sceneLog?.lane_state && (
              <div className="flex items-center gap-2">
                <label className="text-[10px] uppercase tracking-wider text-muted-foreground whitespace-nowrap">
                  Lane
                </label>
                <Badge variant="secondary" className="text-[10px] font-mono">
                  {sceneLog.lane_state}
                </Badge>
              </div>
            )}

            {/* ─── 可行駛空間 ─── */}
            {sceneLog?.free_space && (
              <div>
                <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Free Space
                </label>
                <p className="font-mono text-[11px] text-foreground/80 mt-0.5 leading-relaxed">
                  {sceneLog.free_space}
                </p>
              </div>
            )}

            <Separator className="opacity-30" />

            {/* ─── 偵測物件列表 ─── */}
            <div>
              <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Detections ({detections.length})
              </label>
              <div className="mt-1 space-y-1">
                {detections.map((det, i) => (
                  <div
                    key={`${det.label}-${i}`}
                    className="flex items-center gap-2 bg-muted/20 rounded px-2 py-1"
                  >
                    {/* 標籤 */}
                    <span className="text-[11px] font-medium w-28 truncate">
                      {det.label}
                    </span>

                    {/* 信心度進度條 */}
                    <div className="flex-1 h-1.5 bg-muted/30 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${confidenceColor(det.confidence)}`}
                        style={{ width: `${det.confidence * 100}%` }}
                      />
                    </div>
                    <span className="font-mono text-[10px] tabular-nums text-muted-foreground w-10 text-right">
                      {(det.confidence * 100).toFixed(0)}%
                    </span>

                    {/* 追蹤 ID */}
                    {det.track_id && (
                      <span className="font-mono text-[9px] text-cyan-500/60">
                        {det.track_id}
                      </span>
                    )}
                  </div>
                ))}
                {detections.length === 0 && (
                  <p className="text-[11px] text-muted-foreground italic">
                    無偵測物件
                  </p>
                )}
              </div>
            </div>

            <Separator className="opacity-30" />

            {/* ─── 追蹤摘要 ─── */}
            <div>
              <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Tracks ({tracks.length})
              </label>
              <div className="mt-1 space-y-0.5">
                {tracks.map((trk) => (
                  <div
                    key={trk.track_id}
                    className="flex items-center gap-2 text-[11px]"
                  >
                    <span className="font-mono text-[10px] text-cyan-500/70 w-14">
                      {trk.track_id}
                    </span>
                    <span className="w-20 truncate">{trk.label}</span>
                    <span className={`text-[10px] ${trackStatusColor(trk.status)}`}>
                      {trk.status}
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground ml-auto tabular-nums">
                      {trk.age_frames}f
                    </span>
                    {trk.velocity_mps !== undefined && (
                      <span className="font-mono text-[10px] text-muted-foreground tabular-nums">
                        {trk.velocity_mps.toFixed(1)}m/s
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* ─── 規劃器動作序列 ─── */}
            {plannerAction && plannerAction.action_sequence.length > 0 && (
              <>
                <Separator className="opacity-30" />
                <div>
                  <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    Action Sequence
                  </label>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {plannerAction.action_sequence.map((action, i) => (
                      <div key={i} className="flex items-center gap-1">
                        <Badge
                          variant="secondary"
                          className="text-[9px] font-mono px-1.5 py-0"
                        >
                          {action}
                        </Badge>
                        {i < plannerAction.action_sequence.length - 1 && (
                          <span className="text-muted-foreground/40 text-[10px]">→</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}

            {/* ─── 航點提示 ─── */}
            {plannerAction && plannerAction.waypoints.length > 0 && (
              <>
                <Separator className="opacity-30" />
                <div>
                  <label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    Waypoints ({plannerAction.waypoints.length})
                  </label>
                  <div className="mt-1 space-y-0.5">
                    {plannerAction.waypoints.map((wp, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 text-[10px] font-mono bg-muted/15 rounded px-1.5 py-0.5"
                      >
                        <span className="text-cyan-500/60 w-4">{i + 1}</span>
                        <span className="tabular-nums">
                          ({wp.x.toFixed(1)}, {wp.y.toFixed(1)})
                        </span>
                        <span className="text-emerald-400/70 tabular-nums">
                          {wp.speed_mps.toFixed(1)}m/s
                        </span>
                        {wp.label && (
                          <span className="text-muted-foreground truncate ml-auto">
                            {wp.label}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
