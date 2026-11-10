// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { RuntimeManager } from './RuntimeManager';
const mocks = vi.hoisted(() => ({invoke: vi.fn()}));
vi.mock('@tauri-apps/api/core', () => ({invoke:mocks.invoke}));
afterEach(() => {cleanup(); vi.resetAllMocks();});
function setup(state = 'READY') {
  mocks.invoke.mockImplementation(async (name, args) => name === 'get_backend_status' ? {state} : args?.method === 'runtime.status' ? {
    pid:456, uptimeSeconds:20, dataRoot:'C:\\Data', webSocket:'127.0.0.1:1234',
    capture:{state:'BLOCKED',detail:'Capture process exited (1)',pid:null,manualPause:false,dependencies:{},inputObserved:false}
  } : {});
  const onClose = vi.fn(), onOpenLogs = vi.fn(), onChanged = vi.fn();
  render(<RuntimeManager {...{onClose,onOpenLogs,onChanged}} />);
  return {onClose,onOpenLogs,onChanged};
}
it('shows real process exit; retry requires confirmation and never controls external applications', async () => {
  const {onChanged} = setup();
  await screen.findByText('Capture process exited (1)');
  fireEvent.click(screen.getByRole('button',{name:'Retry'}));
  expect(screen.getByRole('alertdialog')).toBeTruthy();
  expect(mocks.invoke).not.toHaveBeenCalledWith('backend_command',{method:'capture.restart',params:{}});
  fireEvent.click(screen.getByRole('button',{name:'Confirm Restart'}));
  await waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith('backend_command',{method:'capture.restart',params:{}}));
  expect(onChanged).toHaveBeenCalled();
});
it('remains accessible offline, disables capture controls, and opens existing logs', async () => {
  const {onOpenLogs} = setup('STOPPED');
  await screen.findByRole('button',{name:'Start Backend'});
  expect((screen.getByRole('button',{name:'Start Capture'}) as HTMLButtonElement).disabled).toBe(true);
  expect(mocks.invoke).not.toHaveBeenCalledWith('backend_command',{method:'runtime.status',params:{}});
  fireEvent.click(screen.getByRole('button',{name:'View / Collect Logs'}));
  expect(onOpenLogs).toHaveBeenCalledOnce();
});
it('cancel leaves backend alive; Escape closes confirmation before modal', async () => {
  const {onClose} = setup();
  await screen.findByRole('button',{name:'Stop Backend'});
  fireEvent.click(screen.getByRole('button',{name:'Stop Backend'}));
  fireEvent.keyDown(document,{key:'Escape'});
  expect(screen.queryByRole('alertdialog')).toBeNull();
  expect(onClose).not.toHaveBeenCalled();
  expect(mocks.invoke).not.toHaveBeenCalledWith('stop_backend');
});
it('admits only one pending lifecycle operation and shows failures', async () => {
  setup();
  await screen.findByRole('button',{name:'Stop Backend'});
  let reject!: (reason: Error)=>void;
  mocks.invoke.mockImplementation((name,args) => name === 'stop_backend' ? new Promise((_resolve,fail)=>{reject=fail;}) : Promise.resolve(name === 'get_backend_status' ? {state:'STOPPED'} : args?.method === 'runtime.status' ? {} : {}));
  fireEvent.click(screen.getByRole('button',{name:'Stop Backend'}));
  const confirm=screen.getByRole('button',{name:'Confirm Stop'});
  fireEvent.click(confirm);fireEvent.click(confirm);
  expect(mocks.invoke.mock.calls.filter(([name])=>name==='stop_backend')).toHaveLength(1);
  expect((screen.getByRole('button',{name:'Close Runtime Manager'}) as HTMLButtonElement).disabled).toBe(true);
  reject(new Error('owned stop failed'));
  await screen.findByText('Command failed. Check runtime status and collect logs before retrying.');
});
it('allows pausing automatic capture even after a blocked child has exited', async () => {
  setup();
  await screen.findByText('Capture process exited (1)');
  fireEvent.click(screen.getByRole('button',{name:'Stop Capture'}));
  fireEvent.click(screen.getByRole('button',{name:'Confirm Stop'}));
  await waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith('backend_command',{method:'capture.stop',params:{}}));
});
it('keeps native backend recovery controls usable when capture status fails', async () => {
  mocks.invoke.mockImplementation(async name => {
    if(name === 'get_backend_status') return {state:'READY'};
    throw new Error('CONTROL_FAILED');
  });
  render(<RuntimeManager onClose={()=>{}} onOpenLogs={()=>{}} onChanged={()=>{}}/>);
  await screen.findByRole('alert');
  expect((screen.getByRole('button',{name:'Stop Backend'}) as HTMLButtonElement).disabled).toBe(false);
});
