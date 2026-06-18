# MA-VLNA Demo Script

> 此腳本專為作品集展示、面試 Demo 與 GitHub 介紹影片設計，主打核心的「Graceful Fallback 防禦機制」與「SafetyGate 決策追蹤」。

## 📌 展示前置準備 (Pre-flight Checklist)

展示前，請確保以下終端機與服務已啟動並備妥：

1. **Supabase 本地或遠端專案**
   - 確認 `SUPABASE_URL` 與 `SUPABASE_KEY` (Anon/Service Role) 已設定於環境變數。
2. **FastAPI Backend (Terminal 1)**
   - 啟動指令：`uvicorn backend.main:app --host 127.0.0.1 --port 8080`
   - 確認終端機能看到所有的 200 OK 路由請求。
3. **Next.js Dashboard (Terminal 2)**
   - 啟動指令：`cd frontend && npm run dev`
   - 開啟瀏覽器進入 `http://localhost:3000`，應能看到無錯誤的主控台畫面。
4. **Agent 執行環境 (Terminal 3)**
   - 切換至專案根目錄，準備輸入展示指令。

---

## 🎬 Act 1: 系統架構與儀表板導覽 (30秒)

**展示重點**：介紹現代化的 Frontend 與 Backend 解耦架構。

**口白腳本**：
「歡迎來到 MA-VLNA (Memory-Augmented Vision-Language Navigation Agent) 的展示。
這是一個專為自動駕駛與機器人設計的『防呆安全架構 (Fail-safe Architecture)』。
畫面上您看到的是基於 Next.js 開發的控制中心 (Dashboard)，它即時從後端的 FastAPI 獲取車輛狀態。
MA-VLNA 最核心的設計理念在於：**無論底層的 VLM 模型多不穩定，安全閘門 (SafetyGate) 都會作為最後一道防線，保證系統不崩潰並採取保守策略。**」

---

## 🎬 Act 2: Mock 模式與本地端 Fallback 展示 (1分鐘)

**展示重點**：展示 LocalStubReasoner 無縫接管，不依賴昂貴 API 也能進行系統開發與除錯。

**操作步驟**：
在 Terminal 3 執行以下指令：
```bash
python -m workers.Autonomous_Driving_Agent --mode mock --steps 30 --force-vlm-every 10
```

**口白腳本**：
「我們首先展示在本地開發時的 Mock 模式。
在這個模式下，系統會啟用模擬攝影機 (Simulator Camera)。為了節省 API 成本與確保無網際網路情況下能繼續開發，我們設計了 Graceful Fallback 機制。
您可以看到終端機上的日誌：系統偵測到未明確指定 VLM，因此自動退回使用 `LocalStub VLM`。
在執行過程中，每逢第 10 幀、20 幀、30 幀，我們設定了強制觸發。您可以從 Dashboard 上的 **VLM Reasoning Panel** 看到這些模擬的決策（如：『前方路徑通暢...』）已經精準地通過 SafetyGate，並轉化為具體的 Planner Action。」

---

## 🎬 Act 3: OpenAI-Compatible 假斷網防禦展示 (1分鐘)

**展示重點**：展示框架對於「網路異常或 API 金鑰失效」的強健性處理。

**操作步驟**：
在 Terminal 3 執行以下指令，明確要求系統使用真實 API（但此時系統中並未填寫有效的金鑰）：
```bash
python -m workers.Autonomous_Driving_Agent --mode mock --steps 30 --force-vlm-every 10 --vlm-provider openai_compatible
```

**口白腳本**：
「接下來，我們展示當系統嘗試連接真實的 VLM 端點 (如 GPT-4V 或本地的 Gemma 4) 時，若是遭遇網路中斷或 API 金鑰未正確設定的情況。
在這個指令中，我們透過 `--vlm-provider openai_compatible` 強制指定後端。
如您在日誌中所見，系統嘗試初始化 `OpenAICompatibleReasoner`，但很快便偵測到『VLM API 未配置』的錯誤。
這時系統並**沒有 Crash**，而是立刻觸發了安全降級，印出了 `直接使用 LocalStubReasoner`。
這種設計極大地提升了車輛在邊緣端 (Edge) 運作的穩定性，當雲端大腦無法連線時，小腦 (Local Planner) 與 Stub 決策會立刻接管，確保車輛安全停止或依靠純視覺規則前進。」

---

## 🎬 Act 4: 軌跡回放與資料留存 (30秒)

**展示重點**：展示所有的遙測數據、場景感知與決策軌跡皆有妥善保存。

**操作步驟**：
切換至 Dashboard 的 **Replay Logs Panel**。

**口白腳本**：
「最後，身為一套具有記憶擴充能力的系統，可解釋性至關重要。
在儀表板的回放區，我們可以看到方才所有的決策步驟（包含了感知物件的 BBox、VLM 的文字輸出，以及 SafetyGate 是否放行的 Boolean 值）皆已被 Supabase 完整存檔。
這不僅能夠協助除錯，這些保存下來的高價值軌跡，也能作為下一次 VLM In-context Learning 的重要提示。」

---

## 📝 總結備忘錄

- **請勿聲稱**：這套系統已經搭載了在真實市區自動駕駛的模型能力。
- **強調賣點**：這套系統的賣點在於**軟體工程上的架構設計、決策鏈的透明化、以及防禦性程式設計 (Defensive Programming)** 帶來的極高穩定性。
- **免責聲明**：這是一個 Research Prototype 與架構概念驗證 (PoC)，並非實際量產的安全關鍵系統 (Non-safety-critical)。
