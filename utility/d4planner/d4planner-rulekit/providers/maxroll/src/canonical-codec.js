'use strict';
// Backward-compatible D12 facade; future versions use the resolver, not this facade.
const definition=require('../../../snapshot-management/compatibility/versions/maxroll-20261023');
const family=require('./canonical-codec-core').createCodecFamily(definition);
const {BoundCanonicalCodec,...legacy}=family;
module.exports={...legacy,D12_COMPATIBILITY:definition.identity,MaxrollD12CanonicalCodec:BoundCanonicalCodec};
