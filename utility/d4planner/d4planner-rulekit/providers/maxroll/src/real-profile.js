'use strict';
const definition=require('../../../snapshot-management/compatibility/versions/maxroll-20261023');
const {createProfileFamily,createRealProfile,REAL_MAXROLL_COMPONENT_FACTORY}=require('./real-profile-core');
const family=createProfileFamily(definition);
const MAXROLL_32173552_REFERENCE=definition.legacyReference;
function createMaxroll32173552RealProfile(config) {
  return createRealProfile(config, MAXROLL_32173552_REFERENCE, {
    providerVersion: 'maxroll-provider/3.2.1.73552-real-v1',
    runtimeVersion: 'maxroll-export-DOjdL1l3/e796b927',
    assetUrlRegex: 'https://maxroll\\.gg/assets/export-DOjdL1l3\\.js(?:[?#].*)?$',
    requireLevelResetTransition: true,
  }, definition.runtimeDefaults);
}

module.exports={MAXROLL_32173552_REFERENCE,MAXROLL_32173552_D12AM6KT_REFERENCE:definition.reference,REAL_MAXROLL_COMPONENT_FACTORY,createMaxroll32173552RealProfile,createMaxroll32173552D12aM6KTCandidateProfile:family.createCandidateProfile,createMaxroll32173552D12aM6KTUniversalProfile:family.createUniversalProfile};
