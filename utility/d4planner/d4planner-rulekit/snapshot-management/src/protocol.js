'use strict';
const Ajv=require('ajv');const {fail}=require('./trust');
const ajv=new Ajv({strict:true,allErrors:true});
ajv.addFormat('date-time',value=>typeof value==='string'&&/^\d{4}-\d\d-\d\dT/.test(value)&&Number.isFinite(Date.parse(value)));
ajv.addSchema(require('../schemas/registry.schema.json'),'registry.schema.json');
ajv.addSchema(require('../schemas/content-version.schema.json'),'content-version.schema.json');
const validate=ajv.compile(require('../schemas/call.schema.json'));
function validateCall(method,params){fail(validate({method,params}),'SNAPSHOT_CALL_SCHEMA_INVALID');}
module.exports={validateCall};
