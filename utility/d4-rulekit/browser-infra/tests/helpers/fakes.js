'use strict';

const { EventEmitter } = require('events');

class FakeCDPSession {
  constructor() {
    this.detached = false;
  }

  async send(method, params) {
    if (this.detached) throw new Error('session detached');
    return { method, params };
  }

  async detach() {
    this.detached = true;
  }
}

class FakePage {
  constructor(context) {
    this.context = context;
    this.closed = false;
  }

  async close() {
    this.closed = true;
  }
}

class FakeContext extends EventEmitter {
  constructor(browser) {
    super();
    this.browser = browser;
    this.closed = false;
    this.pages = [];
    this.sessions = [];
  }

  async newPage() {
    if (this.closed) throw new Error('context closed');
    const page = new FakePage(this);
    this.pages.push(page);
    return page;
  }

  async newCDPSession() {
    if (this.closed) throw new Error('context closed');
    const session = new FakeCDPSession();
    this.sessions.push(session);
    return session;
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    for (const page of this.pages) await page.close();
    for (const session of this.sessions) await session.detach();
    this.emit('close');
  }
}

class FakeBrowser extends EventEmitter {
  constructor(launcher, contextDelayMs = 0) {
    super();
    this.launcher = launcher;
    this.contextDelayMs = contextDelayMs;
    this.connected = true;
    this.contexts = [];
  }

  isConnected() {
    return this.connected;
  }

  async newContext() {
    if (!this.connected) throw new Error('browser disconnected');
    if (this.contextDelayMs) {
      await new Promise(resolve => setTimeout(resolve, this.contextDelayMs));
    }
    if (!this.connected) throw new Error('browser disconnected');
    const context = new FakeContext(this);
    this.contexts.push(context);
    return context;
  }

  async close() {
    if (!this.connected) return;
    for (const context of this.contexts) await context.close();
    this.connected = false;
    this.launcher.connected -= 1;
    this.emit('disconnected');
  }

  async crash() {
    await this.close();
  }
}

class FakeLauncher {
  constructor({ contextDelayMs = 0, launchDelayMs = 0 } = {}) {
    this.contextDelayMs = contextDelayMs;
    this.launchDelayMs = launchDelayMs;
    this.launchCount = 0;
    this.connected = 0;
    this.peakConnected = 0;
    this.browsers = [];
    this.launchOptions = [];
  }

  async launch(options) {
    if (this.launchDelayMs) await new Promise(resolve => setTimeout(resolve, this.launchDelayMs));
    this.launchCount += 1;
    this.connected += 1;
    this.peakConnected = Math.max(this.peakConnected, this.connected);
    this.launchOptions.push(options);
    const browser = new FakeBrowser(this, this.contextDelayMs);
    this.browsers.push(browser);
    return browser;
  }

  latest() {
    return this.browsers.at(-1);
  }
}

module.exports = { FakeBrowser, FakeContext, FakeLauncher };
