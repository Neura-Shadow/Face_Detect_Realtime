'use client';

/**
 * 回放日誌面板 — ReplayLogsPanel
 * 時間軸事件日誌：觸發事件、規劃器覆寫、安全停車、VLM 回應、操作員決策
 * 支援分類篩選標籤
 */

import { useState, useMemo } from 'react';
import type { TelemetryEntry, EventType } from '@/types/schemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

interface ReplayLogsPanelProps {
  events: TelemetryEntry[];
}

/* ─── 篩選標籤定義 ─── */
type FilterTab = 'all' | 'triggers' | 'planner' | 'safety' | 'vlm' | 'system';

const filterConfig: Record<FilterTab, { label: string; eventTypes: EventType[] | null }> = {
  all: { label: '全部', eventTypes: null },
  triggers: {
    label: '觸發',
    eventTypes: ['vlm_triggered', 'request_review'],
  },
  planner: {
    label: '規劃器',
    eventTypes: ['planner_override'],
  },
  safety: {
    label: '安全',
    eventTypes: ['safe_stop'],
  },
  vlm: {
    label: 'VLM',
    eventTypes: ['vlm_triggered', 'vlm_completed', 'vlm_rejected'],
  },
  system: {
    label: '系統',
    eventTypes: ['system_heartbeat', 'speed_change', 'route_deviation', 'memory_replay'],
  },
};

/* ─── 事件類型顏色對應 ─── */
const eventTypeColors: Record<EventType, string> = {
  vlm_triggered: 'bg-cyan-900/80 text-cyan-300 border-cyan-700',
  vlm_completed: 'bg-cyan-900/60 text-cyan-400 border-cyan-700',
  vlm_rejected: 'bg-red-900/80 text-red-300 border-red-700',
  safe_stop: 'bg-orange-900/80 text-orange-300 border-orange-700',
  request_review: 'bg-amber-900/80 text-amber-300 border-amber-700',
  planner_override: 'bg-purple-900/80 text-purple-300 border-purple-700',
  memory_replay: 'bg-emerald-900/80 text-emerald-300 border-emerald-700',
  speed_change: 'bg-blue-900/60 text-blue-300 border-blue-700',
  route_deviation: 'bg-amber-900/60 text-amber-400 border-amber-700',
  system_heartbeat: 'bg-zinc-800 text-zinc-400 border-zinc-600',
};

/* ─── 事件時間軸圓點顏色 ─── */
const dotColors: Record<EventType, string> = {
  vlm_triggered: 'bg-cyan-500',
  vlm_completed: 'bg-cyan-400',
  vlm_rejected: 'bg-red-500',
  safe_stop: 'bg-orange-500',
  request_review: 'bg-amber-500',
  planner_override: 'bg-purple-500',
  memory_replay: 'bg-emerald-500',
  speed_change: 'bg-blue-400',
  route_deviation: 'bg-amber-400',
  system_heartbeat: 'bg-zinc-500',
};

/* ─── 相對時間格式化 ─── */
function relativeTime(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const seconds = Math.floor(diff / 1000);

  if (seconds < 10) return '剛剛';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function ReplayLogsPanel({ events }: ReplayLogsPanelProps) {
  const [activeTab, setActiveTab] = useState<FilterTab>('all');

  /* ─── 依篩選條件過濾事件 ─── */
  const filteredEvents = useMemo(() => {
    const config = filterConfig[activeTab];
    if (!config.eventTypes) return events;
    const typeSet = new Set(config.eventTypes);
    return events.filter((e) => typeSet.has(e.event_type));
  }, [events, activeTab]);

  return (
    <Card className="h-full flex flex-col border-border/50 bg-card/80">
      <CardHeader className="pb-2 pt-3 px-3 flex-shrink-0 space-y-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-medium uppercase tracking-widest text-muted-foreground flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
            事件日誌
          </CardTitle>
          <span className="text-[10px] text-muted-foreground font-mono">
            {filteredEvents.length} events
          </span>
        </div>

        {/* ─── 篩選標籤列 ─── */}
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as FilterTab)}>
          <TabsList className="h-6 bg-muted/30 p-0.5">
            {Object.entries(filterConfig).map(([key, cfg]) => (
              <TabsTrigger
                key={key}
                value={key}
                className="text-[9px] px-2 py-0.5 h-5 data-[state=active]:bg-background"
              >
                {cfg.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </CardHeader>

      <CardContent className="flex-1 px-3 pb-3 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="space-y-0.5">
            {filteredEvents.map((event, idx) => (
              <div
                key={`${event.timestamp}-${idx}`}
                className="relative flex gap-2 py-1.5 group"
              >
                {/* 時間軸線與圓點 */}
                <div className="flex flex-col items-center flex-shrink-0 w-3">
                  <div className={`w-2 h-2 rounded-full ${dotColors[event.event_type]} flex-shrink-0 mt-0.5`} />
                  {idx < filteredEvents.length - 1 && (
                    <div className="w-px flex-1 bg-border/30 mt-0.5" />
                  )}
                </div>

                {/* 事件內容 */}
                <div className="flex-1 min-w-0 space-y-0.5">
                  {/* 頂行：時間 + 事件類型 Badge */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="font-mono text-[9px] text-muted-foreground tabular-nums w-14 flex-shrink-0">
                      {relativeTime(event.timestamp)}
                    </span>
                    <Badge
                      className={`text-[8px] font-mono border px-1 py-0 h-3.5 ${eventTypeColors[event.event_type]}`}
                    >
                      {event.event_type}
                    </Badge>
                    {event.current_action && (
                      <Badge
                        variant="secondary"
                        className="text-[8px] font-mono px-1 py-0 h-3.5"
                      >
                        {event.current_action}
                      </Badge>
                    )}
                  </div>

                  {/* 詳細描述 */}
                  {event.details && (
                    <p className="text-[10px] text-muted-foreground leading-relaxed">
                      {event.details}
                    </p>
                  )}

                  {/* 速度與安全模式 */}
                  <div className="flex items-center gap-2 text-[9px] text-muted-foreground/70">
                    <span className="font-mono tabular-nums">
                      {event.current_speed.toFixed(1)} m/s
                    </span>
                    {event.safe_mode && (
                      <span className="text-red-400">SAFE MODE</span>
                    )}
                    {event.vlm_active && (
                      <span className="text-cyan-400">VLM</span>
                    )}
                  </div>
                </div>
              </div>
            ))}

            {filteredEvents.length === 0 && (
              <div className="flex items-center justify-center h-16">
                <p className="text-xs text-muted-foreground italic">
                  此分類無事件
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
