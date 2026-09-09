const assert = require('node:assert/strict');
const { mkdtempSync, unlinkSync, rmdirSync } = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');
const { test } = require('node:test');
const { Collection, Events, PermissionsBitField, PermissionFlagsBits } = require('discord.js');
const { createBot } = require('../main');
const { createDatabase } = require('../db');

const SENDER = '111111111111111111';
const RECEIVER = '222222222222222222';

function fixture(t) {
    const database = createDatabase(':memory:');
    const client = createBot(database);
    t.after(async () => {
        await client.destroy();
        database.close();
    });

    const receiver = { id: RECEIVER, user: { username: 'Kris' }, displayName: 'Kris Dreemurr' };
    const cache = new Collection([[RECEIVER, receiver]]);
    const guild = {
        members: {
            cache,
            async fetch(id) {
                if (cache.has(id)) return cache.get(id);
                throw Object.assign(new Error('Unknown Member'), { code: 10007 });
            },
        },
    };
    const handleMessage = client.listeners(Events.MessageCreate)[0];

    async function send(content, options = {}) {
        const replies = [];
        const message = {
            content,
            author: { id: SENDER, username: 'Ralsei', bot: false },
            guild,
            member: { permissions: new PermissionsBitField() },
            inGuild() { return this.guild !== null; },
            ...options,
            channel: { async send(text) { replies.push(text); } },
        };
        await handleMessage(message);
        return replies;
    }

    return { database, client, send };
}

test('prefix routing preserves ping, help, aliases, and ignores bots and unrelated messages', async t => {
    const { client, send } = fixture(t);
    assert.deepEqual(await send('r.ping'), ['Pong!']);
    assert.match((await send('r.help'))[0], /r\.addbalance/);
    for (const content of ['hello', '!ping', 'r.', 'r.unknown']) {
        assert.deepEqual(await send(content), []);
    }
    assert.deepEqual(await send('r.daily', { author: { id: SENDER, bot: true } }), []);
    for (const alias of ['saldo', 'atm', 'bal']) {
        assert.equal(client.commands.get(alias), client.commands.get('balance'));
    }
    for (const alias of ['transferir', 'pix', 'pagar']) {
        assert.equal(client.commands.get(alias), client.commands.get('pay'));
    }
});

test('balance creates users with zero coins and reports existing balances through aliases', async t => {
    const { database, send } = fixture(t);
    assert.deepEqual(await send('r.balance'), ['Ralsei, seu saldo é: 0 TigerCoins.']);
    database.addBalance(SENDER, 1234);
    assert.match((await send('r.saldo'))[0], /1234 TigerCoins/);
    assert.equal(database.getUser(SENDER).discord_id, SENDER);
});

test('daily credits one reward, rejects simultaneous repeats, and expires after 24 hours', async t => {
    const { database, send } = fixture(t);
    let now = 1000000000;
    t.mock.method(Date, 'now', () => now);
    database.addBalance(SENDER, 1000);

    const results = await Promise.all([send('r.daily'), send('r.daily')]);
    const reward = database.getUser(SENDER).balance - 1000;
    assert.ok(reward >= 5000 && reward <= 10000);
    assert.match(results[0][0], new RegExp(`recompensa diária de ${reward} TigerCoins`));
    assert.match(results[1][0], /a cada 24 horas/);

    const previousBalance = database.getUser(SENDER).balance;
    now += 24 * 60 * 60 * 1000;
    await send('r.daily');
    const nextReward = database.getUser(SENDER).balance - previousBalance;
    assert.ok(nextReward >= 5000 && nextReward <= 10000);
});

test('pay resolves mentions, IDs, and quoted member names and conserves the total balance', async t => {
    const { database, send } = fixture(t);
    database.addBalance(SENDER, 1000);
    for (const command of [
        `r.pay <@${RECEIVER}> 100`,
        `r.pix ${RECEIVER} 100`,
        'r.pagar "Kris Dreemurr" 100',
        'r.transferir Kris 100',
    ]) {
        assert.match((await send(command))[0], /transferiu 100 TigerCoins para Kris/);
    }
    assert.equal(database.getUser(SENDER).balance, 600);
    assert.equal(database.getUser(RECEIVER).balance, 400);
    assert.match((await send(`r.pay ${RECEIVER} 601`))[0], /não tem saldo suficiente/);
    assert.equal(database.getUser(SENDER).balance, 600);
    assert.equal(database.getUser(RECEIVER).balance, 400);
});

test('pay rejects invalid values, missing arguments, unknown members, and DMs', async t => {
    const { database, send } = fixture(t);
    database.addBalance(SENDER, 1000);
    for (const amount of ['0', '-1', '1.5', '100abc', '1e2', '9007199254740992']) {
        assert.match((await send(`r.pay ${RECEIVER} ${amount}`))[0], /inteiro maior que zero/);
    }
    assert.match((await send('r.pay'))[0], /Use: r\.pay/);
    assert.match((await send('r.pay 333333333333333333 100'))[0], /Membro não encontrado/);
    assert.match((await send(`r.pay ${RECEIVER} 100`, { guild: null, member: null }))[0], /servidor/);
    assert.equal(database.getUser(SENDER).balance, 1000);
    assert.equal(database.getUser(RECEIVER).balance, 0);
});

test('addbalance requires Administrator permission and denies use in DMs', async t => {
    const { database, send } = fixture(t);
    const command = `r.addbalance ${RECEIVER} 500`;
    assert.match((await send(command))[0], /precisa ser administrador/);
    assert.match((await send(command, { guild: null, member: null }))[0], /precisa ser administrador/);
    assert.equal(database.getUser(RECEIVER).balance, 0);
    const admin = { permissions: new PermissionsBitField(PermissionFlagsBits.Administrator) };
    assert.match((await send(command, { member: admin }))[0], /adicionou 500 TigerCoins/);
    assert.equal(database.getUser(RECEIVER).balance, 500);
});

test('database rolls back failed transfers and self-transfers leave balances unchanged', t => {
    const { database } = fixture(t);
    database.addBalance(SENDER, 1000);
    database.addBalance(RECEIVER, Number.MAX_SAFE_INTEGER);
    assert.throws(() => database.transfer(SENDER, RECEIVER, 100), RangeError);
    assert.equal(database.getUser(SENDER).balance, 1000);
    assert.equal(database.getUser(RECEIVER).balance, Number.MAX_SAFE_INTEGER);
    database.transfer(SENDER, SENDER, 100);
    assert.equal(database.getUser(SENDER).balance, 1000);
    assert.throws(() => database.addBalance(SENDER, -100), RangeError);
});

test('database reads the Python table schema and persists updates across restarts', () => {
    const directory = mkdtempSync(path.join(os.tmpdir(), 'ralseibot-test-'));
    const filename = path.join(directory, 'bot.db');
    let database;
    try {
        const legacy = new DatabaseSync(filename);
        try {
            legacy.exec('CREATE TABLE users (id INTEGER NOT NULL PRIMARY KEY, discord_id VARCHAR UNIQUE, balance INTEGER)');
            legacy.prepare('INSERT INTO users (discord_id, balance) VALUES (?, ?)').run(SENDER, 4321);
        } finally {
            legacy.close();
        }

        database = createDatabase(filename);
        assert.equal(database.getUser(SENDER).balance, 4321);
        database.transfer(SENDER, RECEIVER, 321);
        database.close();
        database = createDatabase(filename);
        assert.equal(database.getUser(SENDER).balance, 4000);
        assert.equal(database.getUser(RECEIVER).balance, 321);
    } finally {
        database?.close();
        unlinkSync(filename);
        rmdirSync(directory);
    }
});
