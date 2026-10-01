import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.api.dependencies import get_gateway, get_token

router = APIRouter(prefix='/estimates/onboarding', tags=['onboarding'])
CATALOG = json.loads((Path(__file__).parents[1] / 'data' / 'onboarding.json').read_text(encoding='utf-8'))
LEVELS = ('beginner', 'intermediate', 'advanced')
KEY = 'combee_onboarding_v1'


def assessment(claimed, attempts):
    level = claimed
    scores = {}
    used = set()
    while level != 'beginner':
        if level not in attempts:
            if set(attempts) != used:
                raise HTTPException(422, '진단 단계가 올바르지 않습니다.')
            return {'completed': False, 'next_level': level, 'scores': scores}
        answers = attempts[level]
        quiz = CATALOG['quizzes'][level]
        if len(answers) != len(quiz) or any(type(x) is not int or not 0 <= x < 3 for x in answers):
            raise HTTPException(422, '각 진단 문항에 답해주세요.')
        used.add(level)
        score = sum(2 for answer, question in zip(answers, quiz) if answer == question[2])
        scores[level] = score
        if score >= 6:
            break
        level = LEVELS[LEVELS.index(level) - 1]
    if set(attempts) != used:
        raise HTTPException(422, '진단 단계가 올바르지 않습니다.')
    return {'completed': True, 'level': level, 'scores': scores}


async def account(gateway, token):
    return await gateway.request('GET', '/auth/v1/user', token=token)


def saved_profile(user):
    record = (user.get('user_metadata') or {}).get(KEY)
    return record if isinstance(record, dict) and record.get('level') in LEVELS else None


async def save(gateway, token, record):
    # This is a user-editable UX preference, never an authorization/role claim.
    await gateway.request('PUT', '/auth/v1/user', token=token, body={'data': {KEY: record}})


@router.get('')
async def get_onboarding(gateway=Depends(get_gateway), token=Depends(get_token)):
    user = await account(gateway, token)
    return {'profile': saved_profile(user), 'levels': CATALOG['levels'],
            'quizzes': {level: [{'question': q[0], 'options': q[1]} for q in questions]
                        for level, questions in CATALOG['quizzes'].items()},
            'surveys': {level: [{'question': q[0], 'options': q[1]} for q in questions]
                        for level, questions in CATALOG['surveys'].items()},
            'keywords': CATALOG['keywords']}


class AssessmentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    claimed_level: Literal['beginner', 'intermediate', 'advanced']
    attempts: dict[str, list[StrictInt]] = Field(default_factory=dict, max_length=2)


@router.post('')
async def diagnose(body: AssessmentInput, gateway=Depends(get_gateway), token=Depends(get_token)):
    await account(gateway, token)
    result = assessment(body.claimed_level, body.attempts)
    if result['completed']:
        record = {'version': 1, 'level': result['level'], 'claimed_level': body.claimed_level,
                  'scores': result['scores'], 'completed_at': datetime.now(timezone.utc).isoformat()}
        await save(gateway, token, record)
        result['profile'] = record
    return result


class PreferencesInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    answers: list[StrictInt] = Field(default_factory=list, max_length=8)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    budget_won: int = Field(ge=300000, le=20000000)
    purpose: Literal['게임', '영상·디자인', '개발', '사무·학습']
    programs: str = Field(min_length=1, max_length=500)
    owned: str = Field(default='', max_length=300)


@router.post('/preferences')
async def preferences(body: PreferencesInput, gateway=Depends(get_gateway), token=Depends(get_token)):
    user = await account(gateway, token)
    profile = saved_profile(user)
    if not profile:
        raise HTTPException(409, '먼저 수준 진단을 완료해주세요.')
    level = profile['level']
    selections = []
    if level == 'advanced':
        allowed = {word for group in CATALOG['keywords'].values() for word in group}
        if body.answers or not body.keywords or any(word not in allowed for word in body.keywords):
            raise HTTPException(422, '선호 키워드를 선택해주세요.')
        selections = list(dict.fromkeys(body.keywords))
    else:
        questions = CATALOG['surveys'][level]
        if body.keywords or len(body.answers) != len(questions) or any(not 0 <= value < 5 for value in body.answers):
            raise HTTPException(422, '수준별 질문을 모두 답해주세요.')
        selections = [f'{i + 1}. {q[0]} → {q[1][value]}' for i, (q, value) in enumerate(zip(questions, body.answers))]
    context = f"사용자 수준: {CATALOG['levels'][level]}\n" + '\n'.join(selections)
    conditions = {'budget_won': body.budget_won, 'purpose': body.purpose,
                  'programs': body.programs, 'owned': body.owned, 'preferences': context}
    record = {**profile, 'preferences': {'answers': body.answers, 'keywords': body.keywords,
              'conditions': conditions, 'updated_at': datetime.now(timezone.utc).isoformat()}}
    await save(gateway, token, record)
    return {'profile': record}
