'use strict';

const { BrowserInfrastructure } = require('./infrastructure');
const { BrowserInfrastructureError, ERROR_CODES } = require('./errors');
const { DEFAULT_CONFIG } = require('./config');

module.exports = {
  BrowserInfrastructure,
  BrowserInfrastructureError,
  ERROR_CODES,
  DEFAULT_CONFIG,
};
