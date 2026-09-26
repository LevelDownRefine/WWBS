/* Connects the active SillyTavern solo chat to the local wwbs pet. */
const BRIDGE_URL = 'http://127.0.0.1:18765';
const TOKEN_KEY = 'wwbs_sillytavern_bridge_key';
let busy = false;

function status(text) {
    const label = document.getElementById('wwbs-bridge-status');
    if (label) label.textContent = text;
}

async function bridgeFetch(path, options = {}) {
    const token = localStorage.getItem(TOKEN_KEY) || '';
    if (!token) throw new Error('请先填写桌宠设置中的酒馆桥接密钥。');
    const response = await fetch(`${BRIDGE_URL}${path}`, {
        ...options,
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        cache: 'no-store',
    });
    if (!response.ok) throw new Error(`桥接请求失败：HTTP ${response.status}`);
    return response.json();
}

function quietPrompt(request) {
    const history = (Array.isArray(request.history) ? request.history : [])
        .filter(item => item && ['user', 'assistant'].includes(item.role) && typeof item.content === 'string')
        .slice(-6)
        .map(item => `${item.role === 'user' ? '用户' : request.character}：${item.content}`)
        .join('\n');
    return `这是从桌宠窗口转来的当前对话。请保持当前角色卡、角色故事、世界书及本会话的既定事实。\n` +
        `只回答用户最后一句，不能编造当前身份、学校、经历、人物关系或剧情事件。\n` +
        `若角色卡与下列桌宠短期对话冲突，以角色卡为准。只输出角色说出的中文台词，一至三句，不要动作描写或解释。\n` +
        (history ? `桌宠最近对话：\n${history}\n` : '') +
        `用户最后一句：${request.message}`;
}

async function handle(request) {
    let text = '';
    let error = '';
    try {
        const context = SillyTavern.getContext();
        const character = context.characters?.[context.characterId];
        if (!character || context.groupId) throw new Error('请在酒馆打开对应角色的单人会话。');
        if (character.name !== request.character) {
            throw new Error(`酒馆当前角色是“${character.name}”，请切换到“${request.character}”后重试。`);
        }
        text = await context.generateQuietPrompt({ quietPrompt: quietPrompt(request) });
        if (typeof text !== 'string' || !text.trim()) throw new Error('酒馆没有生成有效文字。');
        status(`已连接：${character.name}`);
    } catch (e) {
        error = e instanceof Error ? e.message : String(e);
        status(error);
    }
    await bridgeFetch('/reply', {
        method: 'POST',
        body: JSON.stringify({ id: request.id, text, error }),
    });
}

async function poll() {
    if (busy || !localStorage.getItem(TOKEN_KEY)) return;
    busy = true;
    try {
        const data = await bridgeFetch('/next');
        if (data.request) await handle(data.request);
        else status('已连接桌宠，等待消息');
    } catch (e) {
        status(e instanceof Error ? e.message : String(e));
    } finally {
        busy = false;
    }
}

function installSettings() {
    const panel = document.getElementById('extensions_settings2');
    if (!panel || document.getElementById('wwbs-bridge-settings')) return;
    const box = document.createElement('div');
    box.id = 'wwbs-bridge-settings';
    box.style.padding = '0.75em';
    const title = document.createElement('strong');
    title.textContent = 'wwbs 桌宠桥接';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = '粘贴桌宠设置中的酒馆桥接密钥';
    input.value = localStorage.getItem(TOKEN_KEY) || '';
    input.style.width = '100%';
    input.addEventListener('change', () => {
        localStorage.setItem(TOKEN_KEY, input.value.trim());
        status('密钥已保存，等待连接');
    });
    const label = document.createElement('div');
    label.id = 'wwbs-bridge-status';
    label.textContent = '等待连接';
    box.append(title, input, label);
    panel.append(box);
}

installSettings();
setInterval(() => { installSettings(); poll(); }, 1200);
