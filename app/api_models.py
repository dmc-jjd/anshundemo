"""Public request models shared by report/template task routes."""
from datetime import date
from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    file_ids:list[str]=Field(default_factory=list)
    paths:list[str]=Field(default_factory=list)
    template_ref:str=''
    report_month:str|None=None
    sheet_index:int|None=None
    mode:str='fallback'
    event_threshold:float|None=Field(default=None,gt=0,le=1)
    issue_number:int|None=Field(default=None,ge=1)
    publication_date:date|None=None
    package:str|None=None
