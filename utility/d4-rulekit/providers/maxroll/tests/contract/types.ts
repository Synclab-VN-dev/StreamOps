import {
  MaxrollProvider,
  type EvaluationResult,
  type ProviderSession,
} from '../../src';

declare const provider: MaxrollProvider;
declare const session: ProviderSession;
provider.getCapabilities();
const result: Promise<EvaluationResult> = session.evaluate({
  buildSchemaVersion: 'maxroll-build/rogue-l50-v1',
  build: {
    class: 'Rogue', level: 50, difficulty: 'Torment I',
    equipment: { Helm: { itemId: 'runic-skullcap', modifiers: [] } },
  },
});
void result;

// @ts-expect-error Provider does not duplicate Application APIs.
provider.listProviders();
