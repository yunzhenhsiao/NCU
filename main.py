import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

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

    intToStr = {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "日"
    }
    
    try:
        # 1. 使用 inner join 串接 course_schedule 與 course_catalog
        # 我們從 course_schedule 開始查，並強制要求必須有對應的 catalog 資料
        query = supabase.table("course_schedule").select(
            "*, course_catalog!inner(*)"
        )

        # 2. 動態過濾 - 注意欄位名稱需與你的 SQL 一致
        
        # 過濾星期 (SQL 裡 day 是 text)
        if criteria.day:
            query = query.eq("day", intToStr.get(criteria.day, str(criteria.day)))
        
        # 過濾節次 (SQL 裡 time 是 text，我們用 in_ 來比對多個節次)
        if criteria.slots:
            # 將 [5, 6] 轉為 ["5", "6"] 以符合 SQL 的 text 型別
            str_slots = [str(s) for s in criteria.slots]
            query = query.in_("time", str_slots)
            
        # 過濾課程類別 (對應 course_catalog 裡的 category)
        if criteria.course_type:
            query = query.eq("course_catalog.required_type", criteria.course_type)
            
        # 過濾系所 (對應 course_catalog 裡的 dept_code)
        if criteria.dept:
            query = query.eq("course_catalog.dept_code", criteria.dept)

        # 3. 執行查詢
        response = query.execute()
        raw_data = response.data

        # 4. 資料整理 (將巢狀的 catalog 資訊拉出來，方便 Dify 閱讀)
        formatted_data = []
        for item in raw_data:
            catalog = item.get("course_catalog", {})
            formatted_data.append({
                "course_id": item.get("course_id"),
                "title": catalog.get("title_zh"),
                "teacher": catalog.get("teacher"),
                "day": item.get("day"),
                "time": item.get("time"),
                "classroom": item.get("classroom"),
                "category": catalog.get("required_type"),
                "dept": catalog.get("dept_code"),
                "credit": catalog.get("credit")
                # day time classroom 以後在同一個變數回傳
            })

        print(f"查詢成功，找到 {len(formatted_data)} 筆節次資料")
        return {"status": "success", "data": formatted_data}

    except Exception as e:
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