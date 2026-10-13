"""Public seed exchange: upload axes only; local settings are never sent."""
import json
import urllib.error
import urllib.parse
import urllib.request

from combat_seed import decode_seed

SERVICE_URL = 'https://wwbs-seed-library.netlify.app/.netlify/functions/seeds'
MAX_RESPONSE_BYTES = 1024*1024


def _request(query=None, payload=None, *, opener=urllib.request.urlopen):
    url = SERVICE_URL+('?' + urllib.parse.urlencode(query) if query else '')
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={
        'User-Agent': 'WWBS/1.5.4', 'Accept': 'application/json', 'Content-Type': 'application/json'},
        method='POST' if data is not None else 'GET')
    try:
        with opener(request, timeout=20) as response:
            body = response.read(MAX_RESPONSE_BYTES+1)
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read(4096)).get('error')
        except (ValueError, AttributeError):
            error = None
        raise RuntimeError(str(error or f'种子库请求失败（{exc.code}），请稍后重试')) from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise RuntimeError('无法连接在线种子库，请检查网络后重试') from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError('种子库返回内容过大')
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError('种子库返回格式无效')
    return result


def upload_seed(seed: str, *, opener=urllib.request.urlopen):
    decoded = decode_seed(seed)
    if not seed.startswith('【') or not decoded.get('seed_name'):
        raise ValueError('请用当前版本生成种子后上传')
    result = _request(payload={'seed': seed}, opener=opener)
    item = result.get('item', {})
    if item.get('name') != decoded['seed_name'] or not isinstance(item.get('id'), str):
        raise ValueError('种子库返回的种子名称不一致')
    return result


def search_seeds(name='', *, opener=urllib.request.urlopen):
    name = name.strip()
    if len(name) > 10:
        raise ValueError('种子名称最多10个字')
    result = _request({'name': name}, opener=opener)
    items = result.get('items')
    if not isinstance(items, list) or len(items) > 50:
        raise ValueError('种子库返回列表无效')
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) \
                or not 1 <= len(item['name']) <= 10 or not isinstance(item.get('id'), str):
            raise ValueError('种子库返回条目无效')
    return items, bool(result.get('truncated'))


def download_seed(identifier: str, *, opener=urllib.request.urlopen) -> str:
    result = _request({'id': identifier}, opener=opener)
    item = result.get('item')
    if not isinstance(item, dict) or item.get('id') != identifier:
        raise ValueError('下载的种子编号不一致')
    seed = item.get('seed')
    decoded = decode_seed(seed)
    if decoded.get('seed_name') != item.get('name'):
        raise ValueError('下载的种子名称不一致')
    return seed
