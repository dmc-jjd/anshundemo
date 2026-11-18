from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.hotspot_api import router


def test_demo_package_is_retrievable_and_labels_every_comment():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/starbridge/demo-package', params={'title': '测试选题', 'source': '微博热榜'})
    assert response.status_code == 200
    body = response.json()
    assert body['demo'] is True
    assert body['topic']['title'] == '测试选题'
    assert body['original']['demo'] is True
    assert body['citizen_comments'] and body['media_comments']
    assert all(row['demo'] for row in body['citizen_comments'] + body['media_comments'])


def test_demo_package_requires_bounded_title():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        for title in ('', '长' * 501):
            assert client.get('/api/starbridge/demo-package', params={'title': title}).status_code == 422
