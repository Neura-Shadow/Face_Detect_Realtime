/**
 * MA-VLNA Supabase 即時訂閱
 * 提供 vehicle_status 與 scene_logs 資料表的即時更新通道
 * 若環境變數未設定則優雅降級（不會擲出例外）
 */

import { createClient, type SupabaseClient, type RealtimeChannel } from '@supabase/supabase-js';
import type { VehicleStatus, SceneLog } from '@/types/schemas';

/* ─── 環境變數 ─── */
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '';

/* ─── 單例 Supabase Client ─── */
let supabase: SupabaseClient | null = null;

/**
 * 取得 Supabase client（若環境變數未設定則回傳 null）
 */
export function getSupabaseClient(): SupabaseClient | null {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    console.warn('[supabase] 環境變數未設定，即時訂閱功能停用');
    return null;
  }
  if (!supabase) {
    supabase = createClient(SUPABASE_URL, SUPABASE_KEY, {
      realtime: {
        params: {
          eventsPerSecond: 10,
        },
      },
    });
  }
  return supabase;
}

/* ═══════════════════════════════════════════════════
   車輛狀態即時訂閱
   監聽 vehicle_status 資料表的 UPDATE 事件
   ═══════════════════════════════════════════════════ */
export function subscribeToVehicleStatus(
  callback: (status: VehicleStatus) => void,
): RealtimeChannel | null {
  const client = getSupabaseClient();
  if (!client) return null;

  const channel = client
    .channel('vehicle-status-changes')
    .on(
      'postgres_changes',
      {
        event: 'UPDATE',
        schema: 'public',
        table: 'vehicle_status',
      },
      (payload) => {
        // 將 payload.new 轉換為 VehicleStatus 型別
        const record = payload.new as VehicleStatus;
        callback(record);
      },
    )
    .subscribe((status) => {
      console.log(`[supabase] vehicle_status 訂閱狀態: ${status}`);
    });

  return channel;
}

/* ═══════════════════════════════════════════════════
   場景日誌即時訂閱
   監聽 scene_logs 資料表的 INSERT 事件
   ═══════════════════════════════════════════════════ */
export function subscribeToSceneLogs(
  callback: (scene: SceneLog) => void,
): RealtimeChannel | null {
  const client = getSupabaseClient();
  if (!client) return null;

  const channel = client
    .channel('scene-log-inserts')
    .on(
      'postgres_changes',
      {
        event: 'INSERT',
        schema: 'public',
        table: 'scene_logs',
      },
      (payload) => {
        const record = payload.new as SceneLog;
        callback(record);
      },
    )
    .subscribe((status) => {
      console.log(`[supabase] scene_logs 訂閱狀態: ${status}`);
    });

  return channel;
}

/* ═══════════════════════════════════════════════════
   取消訂閱
   ═══════════════════════════════════════════════════ */
export function unsubscribe(channel: RealtimeChannel | null): void {
  if (!channel) return;
  const client = getSupabaseClient();
  if (client) {
    client.removeChannel(channel);
  }
}
