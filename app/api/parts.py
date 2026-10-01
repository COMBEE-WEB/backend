from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.api.dependencies import get_gateway

router = APIRouter(prefix='/parts', tags=['parts'])
FIELDS = 'id,category,name,manufacturer,model_name,description,image_url,source_url,specs,lowest_price'
CATEGORIES = set(('cpu cpu_cooler gpu memory storage motherboard power_supply case accessory '
                  'capture_card case_fan chair desk headphones keyboard laptop lighting microphone '
                  'monitor mouse mousepad network_card os prebuilt_desktop sound_card speaker stand '
                  'thermal_compound vr_headset webcam').split())


@router.get('')
async def list_parts(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                     category: str | None = Query(None, min_length=1, max_length=40, pattern=r'^[a-z_]+$'),
                     q: str = Query('', max_length=100),
                     manufacturer: str = Query('', max_length=100),
                     gateway=Depends(get_gateway)):
    if category and category not in CATEGORIES:
        raise HTTPException(422, '올바른 부품 분류를 선택해주세요.')
    params = {'select': FIELDS, 'is_active': 'eq.true', 'order': 'id.asc',
              'limit': str(limit + 1), 'offset': str(offset)}
    if category:
        params['category'] = f'eq.{category}'
    # Keep user input inside single-column filters, never interpolate OR syntax.
    def literal(value):
        return value.strip().replace('\\', '\\\\').replace('*', '\\*').replace('%', '\\%').replace('_', '\\_')
    if q.strip():
        params['name'] = 'ilike.%' + literal(q) + '%'
    if manufacturer.strip():
        params['manufacturer'] = 'ilike.' + literal(manufacturer)
    rows = await gateway.request('GET', '/rest/v1/parts', params=params)
    return {'items': rows[:limit], 'has_more': len(rows) > limit,
            'limit': limit, 'offset': offset}


@router.get('/{part_id}')
async def get_part(part_id: int = Path(gt=0), gateway=Depends(get_gateway)):
    rows = await gateway.request('GET', '/rest/v1/parts', params={
        'select': FIELDS, 'id': f'eq.{part_id}', 'is_active': 'eq.true', 'limit': '1',
    })
    if not rows:
        raise HTTPException(404, '부품을 찾을 수 없습니다.')
    return rows[0]
