import os
from fastapi import FastAPI
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
    course_name: Optional[str] = None
    day: Optional[int] = None
    slots: Optional[List[int]] = None
    course_type: Optional[str] = None  # 必修, 選修, 通識, 語言, 或 None
    user_dept: Optional[str] = None    # 來自 Dify 的使用者系所 (例如: 資管系)
    user_year: Optional[str] = None    # 來自 Dify 的使用者年級 (例如: 大三)

@app.post("/api/v1/courses/search")
async def search_courses(criteria: SearchCriteria):
    if criteria.course_type == "系上選修":
        criteria.course_type = "選修"
    
    print(f"--- 收到請求 ---")
    print(f"原始資料: {criteria}")
    
    intToStr = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}
    strToStr2 = {"1": "一年級", "2": "二年級", "3": "三年級", "4": "四年級"}
    target_year_str = strToStr2.get(str(criteria.user_year)) if criteria.user_year else None
    
    try:

        if criteria.course_name:
            print(f"正在知識庫搜尋關鍵字: {criteria.course_name}")
            # 使用 .ilike 進行模糊搜尋 (Case-insensitive)
            # %關鍵字% 代表包含該字串
            kb_response = supabase.table("knowledge_base") \
                .select("*") \
                .ilike("course_name", f"%{criteria.course_name}%") \
                .execute()
            
            kb_data = []
            for row in kb_response.data:
                # row 才是字典，可以使用 .get()
                kb_data.append({
                    "course_name": row.get("course_name"),
                    "teacher": row.get("teacher"),
                    "basic_info": row.get("basic_info"),
                    "syllabus_summary": row.get("syllabus_summary"),
                    "priority_logic": row.get("priority_logic")
                })

            print(f"輸出內容: {kb_data}")
            print(f"已加入課程: {kb_response.data[0].get('course_name') if kb_response.data else None}")

            # 直接回傳該列所有資訊，或者你可以照原本格式封裝
            return {
                "status": "success", 
                "source": "knowledge_base",
                "count": len(kb_data), 
                "data": kb_data
            }
        

        # 1. 核心查詢 (使用 !inner 讓 relation 的篩選能生效)
        # 注意：要在 select 裡對子表做篩選，語法是 子表(欄位).eq.值
        query = supabase.table("course_schedule").select(
            "*, course_catalog(*, course_relation(*))" 
        )

        # 2. 基礎過濾：時間
        if criteria.day:
            query = query.eq("day", intToStr.get(criteria.day, str(criteria.day)))
        if criteria.slots:
            query = query.in_("time", [str(s) for s in criteria.slots])

        # 3. 進階邏輯過濾
        # if criteria.course_type:
        #     # 改用 ilike 避免「必修(半年)」之類的匹配失敗
        #     query = query.ilike("course_catalog.required_type", f"%{criteria.course_type}%")

        
        response = query.execute()
        # 正確寫法
        print(f"查詢完成，資料筆數: {len(response.data) if response.data is not None else 0}")
        raw_data = response.data

        formatted_data = []
        for item in raw_data:
            print(item.keys())
            catalog = item.get("course_catalog", {})
            print(catalog)
            if not catalog:
                missing_id = item.get('course_id')
                print(f"⚠️ 警告: 課表中的課程 ID [{missing_id}] (長度:{len(missing_id) if missing_id else 0}) 在目錄中找不到")
                continue
            
            relations = catalog.get("course_relation", [])
            
            # 診斷：印出這門課抓到的所有關聯
            print(f"--- 診斷課程: {catalog.get('title_zh')} ---")
            print(f"系所: {catalog.get('dept_code')}, 年級: {[r.get('year_level') for r in relations]}")

            # 5. 二次檢查：必須有一筆 relation 同時滿足「系所包含」AND「年級一致」
            if criteria.course_type in ["必修", "選修"]:
                # 必須在 relations 陣列中，找到「任一筆」同時符合系所與年級的資料
                is_target_course = False
                
                for r in relations:
                    db_dept = r.get("dept_name") or ""
                    db_year = r.get("year_level") or ""
                    
                    # 考慮到字串匹配（例如：資工系 vs 資訊工程學系）
                    dept_match = (criteria.user_dept in db_dept) or (db_dept in criteria.user_dept)
                    year_match = (db_year == target_year_str)
                    course_match = (catalog.get("required_type") or catalog.get("category")) == criteria.course_type
                    
                    if dept_match and year_match and course_match:
                        is_target_course = True
                        break # 只要找到一筆符合，這門課就是我們要的
                
                if not is_target_course:
                    print(f"結果：跳過（不屬於 {criteria.user_dept} {target_year_str}）")
                    continue
            if criteria.course_type == "通識":
                # 通識課只要類別符合即可，不用管 relation
                if (catalog.get("required_type") or catalog.get("category")) != "通識":
                    print(f"結果：跳過（類別不符）")
                    continue

            if criteria.course_type == "語言":
                # 語言課只要類別符合即可，不用管 relation
                if (catalog.get("required_type") or catalog.get("category")) != "語言":
                    print(f"結果：跳過（類別不符）")
                    continue

            if criteria.course_type == "體育":
                # 體育課只要類別符合即可，不用管 relation
                if (catalog.get("required_type") or catalog.get("category")) != "體育":
                    print(f"結果：跳過（類別不符）")
                    continue

            formatted_data.append({
                "title": catalog.get("title_zh"),
                "teacher": catalog.get("teacher"),
                "timeClassroom": catalog.get("raw_time_classroom"),
                "category": catalog.get("required_type") or catalog.get("category"),
                "dep": catalog.get("dept_code"),
                "cre": catalog.get("credit"),
                "year": [r.get("year_level") for r in relations],
                "course_url": catalog.get("syallabus_url")
            })
            print(f"輸出內容: {formatted_data}")
            print(f"已加入課程: {catalog.get('title_zh')}")

        return {"status": "success", "count": len(formatted_data), "data": formatted_data}

    except Exception as e:
        import traceback
        print(f"!!! 後端出錯了 !!!\n{traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# 使用方法
# 先打 python main.py 啟動後端
# 開 ngrok 打 ngrok http 8000