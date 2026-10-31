'use strict';

const { MaxrollBuildMapper } = require('./build-mapper');
const {
  CLASS_FIXTURE_SCHEMA_VERSION,
  MATRIX_SCHEMA_VERSION,
  MaxrollClassFixtureCapturer,
} = require('./class-fixture-capture');
const {
  CANONICAL_SCHEMA_VERSION,
  CODEC_VERSION,
  D12_COMPATIBILITY,
  MaxrollD12CanonicalCodec,
  MaxrollEntityCatalog,
  loadMaxrollEntityCatalog,
} = require('./canonical-codec');
const {
  EXPORT_SCHEMA_VERSION,
  exportMaxrollBuildFromSnapshot,
  listMaxrollBuildProfilesFromSnapshot,
} = require('./build-export');
const { MaxrollComponentFactory } = require('./component-factory');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const {
  ATTESTATION_SCHEMA_VERSION,
  attestMaxrollBuildFixture,
} = require('./fixture-attestation');
const { METRIC_CATALOG } = require('./metric-catalog');
const { MaxrollMetricsExtractor } = require('./metrics-extractor');
const { MaxrollPatchProfile } = require('./patch-profile');
const { MaxrollProvider } = require('./provider');
const { MaxrollRuntimeAdapter } = require('./runtime-adapter');
const { MaxrollSession } = require('./session');
const { RealMaxrollMetricsExtractor } = require('./real-metrics-extractor');
const { RealMaxrollRuntimeAdapter } = require('./real-runtime-adapter');
const {
  NativeStateMaxrollRuntimeAdapter,
  createD12NativeLoaderMetadata,
} = require('./native-state-runtime-adapter');
const { UniversalMaxrollBuildMapper, CHANGE_TYPES } = require('./universal-build-mapper');
const { UniversalMaxrollComponentFactory } = require('./universal-component-factory');
const {
  MAXROLL_32173552_D12AM6KT_REFERENCE,
  MAXROLL_32173552_REFERENCE,
  REAL_MAXROLL_COMPONENT_FACTORY,
  createMaxroll32173552D12aM6KTCandidateProfile,
  createMaxroll32173552D12aM6KTUniversalProfile,
  createMaxroll32173552RealProfile,
} = require('./real-profile');

module.exports = {
  ATTESTATION_SCHEMA_VERSION,
  CANONICAL_SCHEMA_VERSION,
  CLASS_FIXTURE_SCHEMA_VERSION,
  CODEC_VERSION,
  D12_COMPATIBILITY,
  MAXROLL_32173552_D12AM6KT_REFERENCE,
  ERROR_CODES,
  EXPORT_SCHEMA_VERSION,
  MATRIX_SCHEMA_VERSION,
  METRIC_CATALOG,
  MaxrollBuildMapper,
  MaxrollClassFixtureCapturer,
  MaxrollD12CanonicalCodec,
  MaxrollEntityCatalog,
  MaxrollComponentFactory,
  MaxrollMetricsExtractor,
  MaxrollPatchProfile,
  MaxrollProvider,
  MaxrollProviderError,
  MaxrollRuntimeAdapter,
  NativeStateMaxrollRuntimeAdapter,
  createD12NativeLoaderMetadata,
  MaxrollSession,
  RealMaxrollMetricsExtractor,
  RealMaxrollRuntimeAdapter,
  UniversalMaxrollBuildMapper,
  UniversalMaxrollComponentFactory,
  CHANGE_TYPES,
  MAXROLL_32173552_REFERENCE,
  REAL_MAXROLL_COMPONENT_FACTORY,
  createMaxroll32173552D12aM6KTCandidateProfile,
  createMaxroll32173552D12aM6KTUniversalProfile,
  createMaxroll32173552RealProfile,
  attestMaxrollBuildFixture,
  exportMaxrollBuildFromSnapshot,
  listMaxrollBuildProfilesFromSnapshot,
  loadMaxrollEntityCatalog,
};
