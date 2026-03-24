from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI()

# 定義接收參數的格式 (對應 Dify 的 JSON Body)
class SearchCriteria(BaseModel):
    day: Optional[int] = None
    slots: Optional[List[int]] = None
    course_type: Optional[str] = "通識"
    dept: Optional[str] = None

@app.post("/api/v1/courses/search")
async def search_courses(criteria: SearchCriteria):
    # 這裡先放假的靜態資料，讓你測試 Dify 的表格呈現
    mock_data = [
        {
            "id": "CC101",
            "name": "人工智慧導論",
            "professor": "王小明",
            "time": "週三 3-4 節",
            "credits": 2,
            "type": "系內選修",
            "link": "https://example.com/syllabus/1"
        },
        {
            "id": "GE202",
            "name": "當代電影藝術",
            "professor": "李華",
            "time": "週五 7-8 節",
            "credits": 2,
            "type": "通識",
            "link": "https://example.com/syllabus/2"
        }
    ]
    
    # 模擬簡單的過濾邏輯
    return {"status": "success", "data": mock_data}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)