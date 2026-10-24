'use strict';

const Ajv = require('ajv/dist/2020');
const schema = require('../d4-build-v1.schema.json');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');

const ajv = new Ajv({ allErrors: true, strict: true, allowUnionTypes: true });
const validate = ajv.compile(schema);

function validateCanonicalSchema(build) {
  if (validate(build)) return;
  const hasUnmappedField = validate.errors.some(error => error.keyword === 'additionalProperties');
  throw new MaxrollProviderError(hasUnmappedField
    ? ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE
    : ERROR_CODES.CANONICAL_BUILD_INVALID,
    'canonical build does not satisfy the published d4-build/v1 JSON Schema', {
      details: {
        errors: validate.errors.map(error => Object.freeze({
          instancePath: error.instancePath,
          keyword: error.keyword,
          message: error.message,
          params: error.params,
        })),
      },
    });
}

module.exports = { validateCanonicalSchema };
