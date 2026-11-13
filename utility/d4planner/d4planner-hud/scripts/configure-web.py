#!/usr/bin/env python3
"""One-time owner provisioning. Never edits firewall, starts services or prints tokens."""
import argparse,hashlib,ipaddress,json,os,pathlib,secrets

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-root',type=pathlib.Path,required=True);p.add_argument('--address',default='127.0.0.1');p.add_argument('--port',type=int,default=6090);p.add_argument('--planner-port',type=int,default=6091);p.add_argument('--certificate',type=pathlib.Path);p.add_argument('--private-key',type=pathlib.Path);a=p.parse_args()
 address=ipaddress.IPv4Address(a.address)
 lan=address in ipaddress.ip_network('10.0.0.0/8') or address in ipaddress.ip_network('172.16.0.0/12') or address in ipaddress.ip_network('192.168.0.0/16')
 if not address.is_loopback and not lan:p.error('Only loopback or RFC1918 LAN addresses are supported')
 if not a.data_root.is_absolute() or not a.data_root.is_dir():p.error('Use the existing absolute D4Planner data root')
 if not 1024<=a.port<=65535 or not 1024<=a.planner_port<=65535 or a.port==a.planner_port:p.error('Use two distinct unprivileged ports')
 if bool(a.certificate)!=bool(a.private_key) or (not address.is_loopback and not a.certificate):p.error('LAN requires a trusted TLS certificate and private key')
 for path in (a.data_root,a.certificate,a.private_key):
  if path:
   if not path.is_absolute() or not path.exists() or any(x.is_symlink() for x in (path,*path.parents)):p.error('Paths must exist, be absolute, and contain no symbolic links')
 private=a.data_root/'private';private.mkdir(mode=0o700,exist_ok=True)
 if private.is_symlink():p.error('Unsafe private directory')
 destination=private/'hud-web-config.json';token_file=private/'hud-web-owner-token.txt'
 if destination.exists() or token_file.exists():p.error('Configuration already provisioned; existing credentials were not replaced')
 token=secrets.token_urlsafe(48)
 config={'address':str(address),'port':a.port,'plannerPort':a.planner_port,'certificate':str(a.certificate) if a.certificate else None,'privateKey':str(a.private_key) if a.private_key else None,'credentials':[{'subject':'owner','sha256':hashlib.sha256(token.encode()).hexdigest(),'permissions':['hud.read','target.select','runtime.control','planner.open','report.read','report.preview','report.submit']}]}
 # Exclusive files: never overwrite a previous credential/configuration.
 def write(path,text):
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
 write(token_file,token+'\n');write(destination,json.dumps(config,indent=2)+'\n')
 print('Configured. Restart HUD, then open '+('https' if a.certificate else 'http')+'://'+str(address)+':'+str(a.port)+'/')
 print('Read the access token locally from private/hud-web-owner-token.txt. Do not put it in a URL or issue.')
if __name__=='__main__':main()
