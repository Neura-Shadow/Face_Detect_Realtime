'use client';

/**
 * 場景記憶面板 — SceneMemoryPanel
 * 顯示 Top-K 相似場景記憶：相似度分數、語義摘要、回放候選、成功旗標、動作序列
 */

import type { SceneMemoryEntry } from '@/types/schemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';

interface SceneMemoryPanelProps {
  memories: SceneMemoryEntry[];
}

/* ─── 相似度分數顏色 ─── */
function similarityColor(score: number): string {
  if (score >= 0.9) return 'bg-emerald-500';
  if (score >= 0.75) return 'bg-cyan-500';
  if (score >= 0.6) return 'bg-amber-500';
  return 'bg-red-500';
}

export function SceneMemoryPanel({ memories }: SceneMemoryPanelProps) {
  // 依相似度降序排列
  const sorted = [...memories].sort((a, b) => b.similarity_score - a.similarity_score);

  return (
    <Card className="h-full flex flex-col border-border/50 bg-card/80">
      <CardHeader className="pb-2 pt-3 px-3 flex-shrink-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-medium uppercase tracking-widest text-muted-foreground flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-purple-500" />
            場景記憶
          </CardTitle>
          <span className="text-[10px] text-muted-foreground font-mono">
            Top-{sorted.length}
          </span>
        </div>
      </CardHeader>

      <CardContent className="flex-1 px-3 pb-3 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="space-y-2">
            {sorted.map((mem, idx) => (
              <div
                key={mem.memory_id}
                className="bg-muted/15 rounded-md border border-border/20 p-2 space-y-1.5"
              >
                {/* 頂部：排名、相似度、旗標 */}
                <div className="flex items-center gap-2">
                  {/* 排名序號 */}
                  <span className="text-[10px] font-mono text-muted-foreground w-4">
                    #{idx + 1}
                  </span>

                  {/* 相似度進度條 */}
                  <div className="flex-1 h-1.5 bg-muted/30 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${similarityColor(mem.similarity_score)}`}
                      style={{ width: `${mem.similarity_score * 100}%` }}
                    />
                  </div>
                  <span className="font-mono text-[11px] tabular-nums font-semibold w-10 text-right">
                    {(mem.similarity_score * 100).toFixed(0)}%
                  </span>

                  {/* 回放候選 */}
                  {mem.is_replay_candidate && (
                    <span className="text-amber-400 text-xs" title="回放候選">⭐</span>
                  )}

                  {/* 成功旗標 */}
                  <span title={mem.success_flag ? '成功' : '失敗'}>
                    {mem.success_flag ? '✅' : '❌'}
                  </span>
                </div>

                {/* 語義摘要 */}
                <p className="text-[11px] text-foreground/80 leading-relaxed">
                  {mem.semantic_summary}
                </p>

                {/* 動作序列（小藥丸） */}
                <div className="flex flex-wrap gap-0.5">
                  {mem.action_sequence.map((action, i) => (
                    <Badge
                      key={i}
                      variant="secondary"
                      className="text-[8px] font-mono px-1 py-0 h-4"
                    >
                      {action}
                    </Badge>
                  ))}
                </div>

                {/* 底部：場景 ID、回放次數、結果 */}
                <div className="flex items-center gap-2 text-[9px] text-muted-foreground">
                  <span className="font-mono truncate max-w-24" title={mem.source_scene_id}>
                    {mem.source_scene_id}
                  </span>
                  <span className="ml-auto">
                    replay: {mem.replay_count}
                  </span>
                  <span className="truncate max-w-20" title={mem.outcome}>
                    {mem.outcome}
                  </span>
                </div>
              </div>
            ))}

            {sorted.length === 0 && (
              <div className="flex items-center justify-center h-24">
                <p className="text-xs text-muted-foreground italic">
                  無相似場景記憶
                </p>
              </div>
            )}
          </div>
          {/* 底部間距 */}
          <div className="h-2" />
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
