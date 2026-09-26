const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function main() {
    const requests = [];
    const storage = new Map([['wwbs_sillytavern_bridge_key', 'test-secret']]);
    let prompt = '';
    const sandbox = {
        document: { getElementById: () => null },
        localStorage: {
            getItem: key => storage.get(key) || null,
            setItem: (key, value) => storage.set(key, value),
        },
        setInterval: () => 1,
        SillyTavern: { getContext: () => ({
            characterId: 0,
            groupId: null,
            characters: [{ name: '爱弥斯' }],
            generateQuietPrompt: async ({ quietPrompt }) => {
                prompt = quietPrompt;
                return '我以前在星炬学院，现在是电子幽灵啦。';
            },
        }) },
        fetch: async (url, options) => {
            requests.push({ url, options });
            return { ok: true, json: async () => url.endsWith('/next')
                ? { request: { id: 'one', character: '爱弥斯', message: '你在哪里上学？', history: [] } }
                : { ok: true } };
        },
    };
    const source = fs.readFileSync(path.join(__dirname, '..', 'sillytavern-extension', 'index.js'), 'utf8');
    vm.runInNewContext(source + '\nglobalThis.__poll = poll;', sandbox);
    await sandbox.__poll();
    assert.match(prompt, /你在哪里上学/);
    assert.match(prompt, /角色卡/);
    assert.equal(requests.length, 2);
    assert.equal(requests[0].options.headers.Authorization, 'Bearer test-secret');
    const reply = JSON.parse(requests[1].options.body);
    assert.equal(reply.id, 'one');
    assert.match(reply.text, /星炬学院/);
}

main().catch(error => { console.error(error); process.exitCode = 1; });
