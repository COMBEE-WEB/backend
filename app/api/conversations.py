import json
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from app.api.dependencies import get_gateway, get_token
from app.api.estimates import ChatMessage, user

router = APIRouter(prefix='/conversations', tags=['conversations'])
PREFIX = 'combee_chat:'
KIND = 'combee_chat_v1'

class StoredMessage(ChatMessage):
    result_id: int | None = Field(default=None, gt=0)

class ConversationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    messages: list[StoredMessage] | None = Field(default=None, min_length=1, max_length=20)
    favorite: bool | None = None

async def owned(gateway, token, conversation_id):
    account = await user(gateway, token)
    rows = await gateway.request('GET', '/rest/v1/pc_builds', token=token, params={
        'select': 'id,description', 'id': 'eq.' + str(conversation_id), 'user_id': 'eq.' + account['id'],
        'name': 'like.' + PREFIX + '*', 'limit': '1'})
    if not rows:
        raise HTTPException(404, '대화를 찾을 수 없습니다.')
    try:
        data = json.loads(rows[0]['description'])
        if data.get('kind') != KIND:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(409, '대화 기록 형식을 읽지 못했습니다.') from None
    return account, data

def update(data, body):
    if body.messages is not None:
        if sum(len(m.content) for m in body.messages) > 8000:
            raise HTTPException(422, '대화가 길어졌습니다. 새 대화를 시작해주세요.')
        data['messages'] = [m.model_dump() for m in body.messages]
        data['title'] = next((m.content[:70] for m in body.messages if m.role == 'user'), 'AI 견적 대화')
    if body.favorite is not None:
        data['favorite'] = body.favorite
    return data

@router.get('')
async def listing(offset: int = Query(0, ge=0), gateway=Depends(get_gateway), token=Depends(get_token)):
    account = await user(gateway, token)
    rows = await gateway.request('GET', '/rest/v1/pc_builds', token=token, params={
        'select': 'id,description,created_at', 'user_id': 'eq.' + account['id'],
        'name': 'like.' + PREFIX + '*', 'order': 'created_at.desc,id.desc', 'limit': '21', 'offset': str(offset)})
    items = []
    for row in rows[:20]:
        try:
            data = json.loads(row['description'])
            if data.get('kind') != KIND:
                continue
            items.append({'id': row['id'], 'title': data['title'], 'favorite': data.get('favorite', False), 'created_at': row['created_at']})
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return {'items': items, 'has_more': len(rows) > 20}

@router.post('')
async def create(body: ConversationInput, gateway=Depends(get_gateway), token=Depends(get_token)):
    if body.messages is None:
        raise HTTPException(422, '저장할 대화가 없습니다.')
    account = await user(gateway, token)
    data = update({'kind': KIND, 'favorite': False}, body)
    rows = await gateway.request('POST', '/rest/v1/pc_builds', token=token, prefer='return=representation', body={
        'user_id': account['id'], 'name': PREFIX + data['title'], 'description': json.dumps(data, ensure_ascii=False), 'total_price': 0, 'is_public': False})
    return {'id': rows[0]['id'], **data}

@router.get('/{conversation_id}')
async def detail(conversation_id: int, gateway=Depends(get_gateway), token=Depends(get_token)):
    _, data = await owned(gateway, token, conversation_id)
    return {'id': conversation_id, **data}

@router.post('/{conversation_id}')
async def edit(conversation_id: int, body: ConversationInput, gateway=Depends(get_gateway), token=Depends(get_token)):
    account, data = await owned(gateway, token, conversation_id)
    data = update(data, body)
    rows = await gateway.request('PATCH', '/rest/v1/pc_builds', token=token, prefer='return=representation',
        params={'id': 'eq.' + str(conversation_id), 'user_id': 'eq.' + account['id'], 'name': 'like.' + PREFIX + '*', 'select': 'id'},
        body={'name': PREFIX + data['title'], 'description': json.dumps(data, ensure_ascii=False)})
    if not rows:
        raise HTTPException(404, '대화를 찾을 수 없습니다.')
    return {'id': conversation_id, **data}

@router.delete('/{conversation_id}')
async def delete(conversation_id: int, gateway=Depends(get_gateway), token=Depends(get_token)):
    account, _ = await owned(gateway, token, conversation_id)
    rows = await gateway.request('DELETE', '/rest/v1/pc_builds', token=token, prefer='return=representation',
        params={'id': 'eq.' + str(conversation_id), 'user_id': 'eq.' + account['id'], 'name': 'like.' + PREFIX + '*', 'select': 'id'})
    if not rows:
        raise HTTPException(404, '대화를 찾을 수 없습니다.')
    return {'deleted': True}
