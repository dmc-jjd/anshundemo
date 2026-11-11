"""Serve an isolated copy; any model call after human action is a test failure."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import uvicorn
import app.main as main
from app.storage import Store
from app.workflow import Dependencies

store=Store(Path(sys.argv[1]));main.store=store
async def forbidden(role,payload):
    store.append_event('d2511637eb694125a92616d2a276bd08',{'type':'unexpected_model_after_human','role':role})
    raise AssertionError('Human final actions must never invoke a model')
main.deps=Dependencies(store,forbidden)
uvicorn.run(main.app,host='127.0.0.1',port=8877,log_level='warning')
