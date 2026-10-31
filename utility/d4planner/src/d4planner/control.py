"""Validation for business requests on the existing managed Backend pipe."""
import re

PROTOCOL = 'd4planner-control/v1'
FIELDS = {'protocolVersion','type','requestId','ownerInstanceId','childInstanceId','generation','method','params'}

def validate_request(command):
    if not isinstance(command, dict) or set(command) != FIELDS or command.get('protocolVersion') != PROTOCOL or command.get('type') != 'request':
        raise ValueError('INVALID_CONTROL_MESSAGE')
    if any(not isinstance(command[k], str) or not 1 <= len(command[k]) <= 160 for k in ('requestId','ownerInstanceId','childInstanceId')) or type(command['generation']) is not int or command['generation'] < 1:
        raise ValueError('INVALID_CONTROL_MESSAGE')
    params = command['params']
    if command['method'] == 'target.list' and params == {}:
        return
    if command['method'] != 'target.select':
        raise ValueError('UNSUPPORTED_METHOD')
    if not isinstance(params, dict) or set(params) != {'targetId','expectedSha256','expectedListRevision'}:
        raise ValueError('INVALID_PARAMETERS')
    if not isinstance(params['targetId'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,63}', params['targetId']):
        raise ValueError('INVALID_PARAMETERS')
    if not isinstance(params['expectedSha256'], str) or not re.fullmatch('[a-f0-9]{64}', params['expectedSha256']):
        raise ValueError('INVALID_PARAMETERS')
    if type(params['expectedListRevision']) is not int or not 0 <= params['expectedListRevision'] <= 9007199254740991:
        raise ValueError('INVALID_PARAMETERS')

async def dispatch(runtime, command, bootstrap):
    envelope = {'protocolVersion':PROTOCOL, 'type':'response',
                'requestId':command.get('requestId'),
                **{key:bootstrap[key] for key in ('ownerInstanceId','childInstanceId','generation')},
                'result':None,'error':None}
    try:
        validate_request(command)
        if any(command[k] != bootstrap[k] for k in ('ownerInstanceId','childInstanceId','generation')):
            raise ValueError('OWNERSHIP_MISMATCH')
        envelope['result'] = await runtime.handle_control(command)
        if envelope['result'] is None:
            raise ValueError('UNSUPPORTED_METHOD')
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) else getattr(exc, 'code', 'CONTROL_FAILED')
        if code not in {'INVALID_CONTROL_MESSAGE','UNSUPPORTED_METHOD','INVALID_PARAMETERS','OWNERSHIP_MISMATCH','TARGET_CHANGED','TARGET_NOT_FOUND','TARGET_INVALID','TARGET_POLICY_INVALID'}:
            code = 'CONTROL_FAILED'
        envelope['error'] = {'code':code,'message':'Backend command failed.', 'retryable':bool(getattr(exc,'retryable',False))}
    return envelope
