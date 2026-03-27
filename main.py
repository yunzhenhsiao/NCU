import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from supabase import create_client, Client

app = FastAPI()

# --- Supabase 設定 ---
# 建議將這些敏感資訊放在 .env 檔案中
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 定義接收參數的格式
class SearchCriteria(BaseModel):
    # 全部改成 Optional[str]，後端邏輯內再轉型或直接查詢
    day: Optional[int] = None
    slots: Optional[List[int]] = None
    course_type: Optional[str] = None
    dept: Optional[str] = None

@app.post("/api/v1/courses/search")
async def search_courses(criteria: SearchCriteria):
    print(f"--- 收到請求 ---")
    print(f"原始資料: {criteria}")
    
    try:
        # 1. 基本查詢 (先選出所有欄位)
        query = supabase.table("course_schedule").select("*")

        # 2. 動態過濾 (請確保欄位名稱與 Supabase 一致)
        if criteria.day:
            # 強制轉為 int 確保跟資料庫型別一致
            query = query.eq("day", int(criteria.day))
        
        if criteria.course_type:
            query = query.eq("type", criteria.course_type)
            
        if criteria.dept:
            # 假設資管系也要看特定系所欄位
            query = query.eq("department", criteria.dept)

        # 3. 執行查詢
        response = query.execute()
        all_data = response.data
        
        # 4. 處理 slots 過濾 (假設 slots 在 DB 是 [1, 2, 3] 陣列)
        filtered_data = all_data
        if criteria.slots and all_data:
            # 找出「只要重疊到任何一節」的課
            filtered_data = [
                course for course in all_data 
                if any(s in (course.get("slots") or []) for s in criteria.slots)
            ]

        print(f"查詢成功，找到 {len(filtered_data)} 筆資料")
        return {"status": "success", "data": filtered_data}

    except Exception as e:
        # 這裡會印出到底是哪一行出錯
        import traceback
        print("!!! 後端出錯了 !!!")
        print(traceback.format_exc()) 
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# 使用方法
# 先打 python main.py 啟動後端
# 開 ngrok 打 ngrok http 8000