import {
  CONTRACT_VERSION,
  D4RuleKitApplication,
  type CalculationProvider,
  type ProviderSession,
} from '../../src';

declare const provider: CalculationProvider;
declare const runtime: ProviderSession;

const app = new D4RuleKitApplication({ providers: [provider] });
app.listProviders();
app.createSession({
  contractVersion: CONTRACT_VERSION,
  providerId: provider.id,
  providerVersion: provider.version,
  snapshotId: null,
  snapshotManifestSha256: null,
  buildSchemaVersion: 'fixture/v1',
  build: {},
});
runtime.close({ signal: new AbortController().signal });

// @ts-expect-error The ninth public operation is intentionally absent.
app.registerProvider(provider);
