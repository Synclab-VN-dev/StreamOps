import { afterEach, describe, expect, it, vi } from 'vitest';
import Ajv2020 from 'ajv/dist/2020';
import schema from '../../d4planner/contracts/release1/v1/schemas/ws.schema.json';
import { HudNotificationClient, type WebSocketLike } from './hud-data-source';
class Socket implements WebSocketLike {
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: {data: string}) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: Record<string, any>[] = [];
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
  receive(message: unknown) { this.onmessage?.({data:JSON.stringify(message)}); }
}
const protocolVersion = 'd4planner-notify/v1';
const committed = (hudRevision = 12, epoch = 'epoch-a') => ({
  protocolVersion, type:'hud.committed', messageId:'event', dbId:'db-a', epoch, hudRevision,
});
const validate = new Ajv2020().compile(schema);
function authenticate(socket: Socket) {
  const accepted = {protocolVersion, type:'hello.accepted', messageId:'accepted', correlationId:socket.sent[0].messageId};
  expect(validate(accepted)).toBe(true);
  socket.receive(accepted);
}
function setup(accept = true) {
  vi.useFakeTimers();
  const sockets: Socket[] = [];
  const reread = vi.fn(), connection = vi.fn();
  const client = new HudNotificationClient({endpoint:'ws://127.0.0.1:12345', credential:'x'.repeat(32),
    origin:'tauri://localhost', reread, connection, reconnectDelaysMs:[10,20], handshakeTimeoutMs:50,
    socketFactory:() => { const s = new Socket(); sockets.push(s); return s; }});
  client.connect();
  const socket = sockets[0];
  socket.onopen?.();
  if (accept) authenticate(socket);
  return {client, socket, sockets, reread, connection};
}
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });
describe('D5 notification-only client', () => {
  it('rereads offline on startup and sends only the contract authentication hello', () => {
    const {socket, reread, connection} = setup(false);
    expect(reread).toHaveBeenCalledTimes(1);
    expect(connection).not.toHaveBeenCalledWith(true);
    expect(validate(socket.sent[0])).toBe(true);
    authenticate(socket);
    expect(reread).toHaveBeenCalledTimes(2);
    expect(socket.sent.map(m => m.type)).toEqual(['hello']);
  });
  it('rereads for duplicate, reordered, gapped and replaced-DB hints without applying metadata as data', () => {
    const {socket, reread} = setup();
    for (const message of [committed(12),committed(12),committed(9),committed(40),committed(1,'restored')]) {
      expect(validate(message)).toBe(true); socket.receive(message);
    }
    expect(reread).toHaveBeenCalledTimes(7);
    expect(reread.mock.calls.every(args => args.length === 0)).toBe(true);
    expect(socket.sent).toHaveLength(1);
  });
  it.each([
    {...committed(),hud:{score:100}}, {...committed(),targets:[]}, {...committed(),type:'hud.snapshot'},
    {...committed(),type:'target.list'}, {...committed(),protocolVersion:'d4planner-ws/v1'},
    {...committed(),hudRevision:-1}, {...committed(),hudRevision:1.5},
    {...committed(),hudRevision:Number.MAX_SAFE_INTEGER+1}, {...committed(),epoch:''},
    {...committed(),dbId:'x'.repeat(161)}, {...committed(),messageId:null}, null,
  ])('rejects messages outside the notification contract: %j', message => {
    const {socket, connection} = setup();
    expect(validate(message)).toBe(false);
    socket.receive(message);
    expect(socket.readyState).toBe(3);
    expect(connection).toHaveBeenLastCalledWith(false);
  });
  it('rejects notifications before authentication', () => {
    const {socket} = setup(false); socket.receive(committed()); expect(socket.readyState).toBe(3);
  });
  it('rejects wrong hello correlation', () => {
    const {socket} = setup(false);
    socket.receive({protocolVersion,type:'hello.accepted',messageId:'a',correlationId:'wrong'});
    expect(socket.readyState).toBe(3);
  });
  it('rejects malformed JSON', () => {
    const {socket} = setup(); socket.onmessage?.({data:'{'}); expect(socket.readyState).toBe(3);
  });
  it('rereads on reconnect and ignores callbacks from the previous connection', () => {
    const {socket,sockets,reread} = setup(); socket.close(); vi.advanceTimersByTime(10);
    const current = sockets[1]; current.onopen?.(); authenticate(current);
    const count = reread.mock.calls.length;
    socket.receive(committed(999)); socket.onclose?.();
    expect(reread).toHaveBeenCalledTimes(count);
    current.receive(committed(1)); expect(reread).toHaveBeenCalledTimes(count+1);
  });
  it('bounds unauthenticated connection timeout and retries', () => {
    const {sockets,connection} = setup(false); vi.advanceTimersByTime(500);
    expect(sockets).toHaveLength(3); expect(connection).not.toHaveBeenCalledWith(true);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('disconnect cancels retries and ignores late open/messages', () => {
    const {client,socket,sockets,reread} = setup(false); client.disconnect();
    const count = reread.mock.calls.length; socket.onopen?.(); socket.receive(committed());
    vi.advanceTimersByTime(500);
    expect(sockets).toHaveLength(1); expect(socket.sent).toHaveLength(1);
    expect(reread).toHaveBeenCalledTimes(count); expect(vi.getTimerCount()).toBe(0);
  });
  it('bounds factory failures while permitting offline reads', () => {
    vi.useFakeTimers(); const reread = vi.fn();
    const socketFactory = vi.fn(() => {throw new Error('offline');});
    const client = new HudNotificationClient({endpoint:'ws://localhost:12345',credential:'x'.repeat(32),
      origin:'tauri://localhost',reread,connection:vi.fn(),socketFactory,reconnectDelaysMs:[10]});
    client.connect(); vi.advanceTimersByTime(100);
    expect(socketFactory).toHaveBeenCalledTimes(2); expect(reread).toHaveBeenCalledTimes(1);
    client.disconnect();
  });
  it('rejects a non-loopback endpoint before opening a socket', () => {
    expect(() => new HudNotificationClient({endpoint:'ws://example.com:12345',credential:'x'.repeat(32),
      origin:'tauri://localhost',reread:vi.fn(),connection:vi.fn(),socketFactory:() => new Socket()}))
      .toThrow('LOOPBACK_REQUIRED');
  });
});
