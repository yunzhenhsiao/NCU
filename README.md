### 🎓 NCU 課程查詢系統 - Backend API

這是 NCU 課程查詢小幫手 的後端服務，負責連接 `Dify` (LLM 平台) 與 `Supabase` (資料庫)。當 `Dify` 接收到使用者的查課意圖後，會呼叫此 `API`，由後端進行精確的資料庫篩選與模糊搜尋，並將優化後的資料回傳給 LLM 進行回覆。

### 🚀 技術棧 (Tech Stack)

核心框架: `FastAPI` - 高效能的 Python Web 框架。

資料庫: `Supabase` - 建立於 PostgreSQL 之上的開源 Firebase 代替方案。

部署平台: Render - 自動化雲端部署服務。

資料操作: `Supabase Python SDK`, `Pydantic` (資料驗證)。

### 🌟 核心功能

智慧路由搜尋:

    關鍵字模式: 當使用者輸入課程名稱時，自動切換至 knowledge_base 表進行課程大綱與優先權邏輯的模糊搜尋 (ilike)。
  
    條件篩選模式: 支援根據星期、節次、課程類別（必選修、通識、語言、體育）進行多維度過濾。

精確的身分匹配:

  整合 `course_relation` 表，自動判別課程是否符合使用者的 系所 與 年級，避免回傳無關的課程資訊。
  
  LLM 效能優化 (Token Optimization):
    
    針對回傳給 Dify 的 JSON 資料進行瘦身，僅保留關鍵欄位，降低 LLM 的 Token 消耗並提升回應速度。
  
  雲端適應性:
  
    支援動態 Port 讀取與環境變數配置，完美適應 Render 部署環境。

### 🛠️ API 規格

搜尋課程 (Search Courses):

  Endpoint: `POST /api/v1/courses/search`
  
  Content-Type: `application/json`
  
  請求參數 (Request Body):

    | 欄位名稱 | 型態 | 說明 |
    | `course_name` | String | 課程名稱關鍵字，輸入後會優先進行知識庫搜尋 |
    | `day` | Integer | 星期幾 (1-7) |
    | `slots` | list[int] | 節次列表 (例如 [1, 2, 3])|
    | `course_type` | string | 類別：必修, 選修, 通識, 語言, 體育|
    | `user_dept` | string | 使用者所屬系所 (例如：資訊管理學系) |
    | `user_year` | string | 使用者年級 (1, 2, 3, 4)|
  
  響應範例 (Response):

    ```json
    {
      "status": "success",
      "count": 1,
      "data": [
        {
          "title": "統計學",
          "teacher": "邱信瑜",
          "timeClassroom": "四234/I1-017",
          "category": "必修",
          "dep": "資管系",
          "cre": 3,
          "year": ["二年級"],
          "course_url": "https://..."
        }
      ]
    }
    
### ⚙️ 本地開發環境設定


1.複製專案:

  `git clone <your-repo-url>`
  
  `cd <repo-folder>`

2.安裝依賴:

  `pip install -r requirements.txt`

3.設定環境變數:

  在根目錄建立 .env 檔案並填入：
  
    SUPABASE_URL=你的Supabase網址
    SUPABASE_KEY=你的Supabase金鑰

4.啟動服務:

  `python main.py`

### 🌐 部署說明 (Render)

1.將程式碼推送到 GitHub。

2.在 Render 建立新的 Web Service 並連結 GitHub Repo。

3.Build Command: pip install -r requirements.txt

4.Start Command: python main.py

5.在 Environment 設定頁面新增 SUPABASE_URL 與 SUPABASE_KEY。
