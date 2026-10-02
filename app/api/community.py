import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_gateway, get_token

router = APIRouter(prefix='/community', tags=['community'])
AUTHOR = 'author:profiles!author_id(nickname,avatar_url)'
POST = 'id,board,author_id,build_id,title,created_at,updated_at,' + AUTHOR
MARKER = 'combee_public_build_v1'


class PostInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    board: Literal['free', 'build_share']
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5000)
    build_id: int | None = Field(default=None, gt=0)


class EditInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5000)


class CommentInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=1500)


class CommentChange(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    content: str | None = Field(default=None, min_length=1, max_length=1500)


async def current_user(gateway, token):
    return await gateway.request('GET', '/auth/v1/user', token=token)


def unpack(row):
    result = dict(row)
    if 'content' in row and row.get('board') == 'build_share':
        try:
            packed = json.loads(row['content'])
            if isinstance(packed, dict) and packed.get('format') == MARKER and isinstance(packed.get('body'), str):
                result['content'] = packed['body']
                result['shared_build'] = packed.get('build')
        except (ValueError, TypeError):
            pass
    return result


async def existing(gateway, post_id, token=None):
    rows = await gateway.request('GET', '/rest/v1/posts', token=token, params={
        'select': POST + ',content', 'id': f'eq.{post_id}', 'board': 'in.(free,build_share)', 'limit': '1'})
    if not rows:
        raise HTTPException(404, '게시글을 찾을 수 없습니다.')
    return rows[0]


@router.get('/posts')
async def list_posts(board: Literal['free', 'build_share'] = 'free', offset: int = Query(0, ge=0),
                     q: str = Query('', max_length=100), gateway=Depends(get_gateway)):
    params = {'select': POST + ',comments(count)', 'board': 'eq.' + board,
              'order': 'created_at.desc,id.desc', 'limit': '21', 'offset': str(offset)}
    if q.strip():
        literal = q.strip().replace('\\', '\\\\').replace('*', '\\*').replace('%', '\\%').replace('_', '\\_')
        params['title'] = 'ilike.%' + literal + '%'
    rows = await gateway.request('GET', '/rest/v1/posts', params=params)
    return {'items': rows[:20], 'has_more': len(rows) > 20}


@router.get('/posts/{post_id}')
async def detail(post_id: int, gateway=Depends(get_gateway)):
    return unpack(await existing(gateway, post_id))


@router.get('/posts/{post_id}/comments')
async def comments(post_id: int, offset: int = Query(0, ge=0), gateway=Depends(get_gateway)):
    await existing(gateway, post_id)
    rows = await gateway.request('GET', '/rest/v1/comments', params={
        'select': 'id,post_id,author_id,content,created_at,updated_at,' + AUTHOR,
        'post_id': f'eq.{post_id}', 'order': 'created_at.asc,id.asc', 'offset': str(offset), 'limit': '51'})
    return {'items': rows[:50], 'has_more': len(rows) > 50}


@router.post('/posts', status_code=201)
async def create(body: PostInput, gateway=Depends(get_gateway), token=Depends(get_token)):
    user = await current_user(gateway, token)
    content = body.content
    if body.board == 'build_share':
        if not body.build_id:
            raise HTTPException(422, '공유할 내 견적을 선택해주세요.')
        builds = await gateway.request('GET', '/rest/v1/pc_builds', token=token, params={
            'select': 'id,description', 'id': f'eq.{body.build_id}', 'user_id': 'eq.' + user['id'], 'limit': '1'})
        if not builds:
            raise HTTPException(403, '본인이 저장한 견적만 첨부할 수 있습니다.')
        try:
            snapshot = json.loads(builds[0]['description'])
            if snapshot.get('version') != 1 or not isinstance(snapshot.get('parts'), list) or not snapshot['parts']:
                raise ValueError()
            # Publish only explicitly previewed parts/prices. Never share prompts,
            # owned-part notes, account metadata, or the original private build.
            parts = [{key: p.get(key) for key in ('id', 'category', 'name', 'quantity', 'lowest_price')}
                     for p in snapshot['parts']]
            shared = {'parts': parts, 'total_price': snapshot.get('total_price')}
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(422, '이전 형식의 견적은 첨부할 수 없습니다. 새 견적을 만들어주세요.') from None
        content = json.dumps({'format': MARKER, 'body': body.content, 'build': shared}, ensure_ascii=False)
    elif body.build_id is not None:
        raise HTTPException(422, '견적은 견적공유게시판에서 첨부해주세요.')
    rows = await gateway.request('POST', '/rest/v1/posts', token=token, prefer='return=representation', body={
        'board': body.board, 'author_id': user['id'], 'title': body.title, 'content': content, 'build_id': body.build_id})
    return {'id': rows[0]['id']}


@router.post('/posts/{post_id}/edit')
async def edit(post_id: int, body: EditInput, gateway=Depends(get_gateway), token=Depends(get_token)):
    user = await current_user(gateway, token)
    row = await existing(gateway, post_id, token)
    if row['author_id'] != user['id']:
        raise HTTPException(403, '내 게시글만 수정할 수 있습니다.')
    previous = unpack(row)
    content = json.dumps({'format': MARKER, 'body': body.content, 'build': previous['shared_build']}, ensure_ascii=False) if 'shared_build' in previous else body.content
    await gateway.request('PATCH', '/rest/v1/posts', token=token, params={'id': f'eq.{post_id}', 'author_id': 'eq.' + user['id']}, body={'title': body.title, 'content': content})
    return {'success': True}


@router.post('/posts/{post_id}/delete')
async def delete(post_id: int, gateway=Depends(get_gateway), token=Depends(get_token)):
    user = await current_user(gateway, token)
    row = await existing(gateway, post_id, token)
    if row['author_id'] != user['id']:
        raise HTTPException(403, '내 게시글만 삭제할 수 있습니다.')
    await gateway.request('DELETE', '/rest/v1/posts', token=token, params={'id': f'eq.{post_id}', 'author_id': 'eq.' + user['id']})
    return {'success': True}


@router.post('/posts/{post_id}/comments', status_code=201)
async def comment(post_id: int, body: CommentInput, gateway=Depends(get_gateway), token=Depends(get_token)):
    user = await current_user(gateway, token)
    await existing(gateway, post_id, token)
    rows = await gateway.request('POST', '/rest/v1/comments', token=token, prefer='return=representation', body={
        'post_id': post_id, 'author_id': user['id'], 'content': body.content})
    return {'id': rows[0]['id']}


@router.post('/comments/{comment_id}/{action}')
async def change_comment(comment_id: int, action: Literal['edit', 'delete'], body: CommentChange | None = None,
                         gateway=Depends(get_gateway), token=Depends(get_token)):
    user = await current_user(gateway, token)
    rows = await gateway.request('GET', '/rest/v1/comments', token=token, params={
        'select': 'id,author_id', 'id': f'eq.{comment_id}', 'limit': '1'})
    if not rows:
        raise HTTPException(404, '댓글을 찾을 수 없습니다.')
    if rows[0]['author_id'] != user['id']:
        raise HTTPException(403, '내 댓글만 변경할 수 있습니다.')
    if action == 'edit' and (not body or body.content is None):
        raise HTTPException(422, '댓글 내용을 입력해주세요.')
    await gateway.request('PATCH' if action == 'edit' else 'DELETE', '/rest/v1/comments', token=token,
                          params={'id': f'eq.{comment_id}', 'author_id': 'eq.' + user['id']},
                          body={'content': body.content} if action == 'edit' else None)
    return {'success': True}


@router.get('/parts/{part_id}/comments')
async def part_comments(part_id: int, offset: int = Query(0, ge=0), gateway=Depends(get_gateway)):
    rows = await gateway.request('GET', '/rest/v1/part_comments', params={
        'select': 'id,part_id,author_id,content,created_at,' + AUTHOR,
        'part_id': f'eq.{part_id}', 'order': 'created_at.desc,id.desc', 'offset': str(offset), 'limit': '21'})
    return {'items': rows[:20], 'has_more': len(rows) > 20}


@router.post('/parts/{part_id}/comments', status_code=201)
async def create_part_comment(part_id: int, body: CommentInput, gateway=Depends(get_gateway), token=Depends(get_token)):
    user = await current_user(gateway, token)
    parts = await gateway.request('GET', '/rest/v1/parts', params={
        'select': 'id', 'id': f'eq.{part_id}', 'is_active': 'eq.true', 'limit': '1'})
    if not parts:
        raise HTTPException(404, '부품을 찾을 수 없습니다.')
    rows = await gateway.request('POST', '/rest/v1/part_comments', token=token, prefer='return=representation', body={
        'part_id': part_id, 'author_id': user['id'], 'content': body.content})
    return {'id': rows[0]['id']}


@router.post('/part-comments/{comment_id}/delete')
async def delete_part_comment(comment_id: int, gateway=Depends(get_gateway), token=Depends(get_token)):
    user = await current_user(gateway, token)
    rows = await gateway.request('GET', '/rest/v1/part_comments', token=token, params={
        'select': 'id,author_id', 'id': f'eq.{comment_id}', 'limit': '1'})
    if not rows:
        raise HTTPException(404, '댓글을 찾을 수 없습니다.')
    if rows[0]['author_id'] != user['id']:
        raise HTTPException(403, '내 댓글만 삭제할 수 있습니다.')
    await gateway.request('DELETE', '/rest/v1/part_comments', token=token,
                          params={'id': f'eq.{comment_id}', 'author_id': 'eq.' + user['id']})
    return {'success': True}
