"""Re-sign the verified current iOS package for an updated Ad Hoc device list."""
from __future__ import annotations
import argparse,datetime as dt,fnmatch,hashlib,json,os,plistlib,stat,subprocess,tempfile,zipfile
from pathlib import Path,PurePosixPath

BUNDLE_ID='com.vexlink.liaoqiao.ios'
TEAM_ID='5V4M77FFRV'
ASSET_ROOT='https://github.com/wgp899-eng/tongiva-releases/releases/download/ios-updates/'

def run(args):
    value=subprocess.run([str(a) for a in args],check=True,capture_output=True,timeout=300)
    return value.stdout

def profile(path):
    return plistlib.loads(run(['security','cms','-D','-i',path]))

def device_hash(devices):
    return hashlib.sha256('\n'.join(sorted(str(d).upper() for d in devices)).encode()).hexdigest()

def permits(value,allowed):
    if isinstance(value,dict):return isinstance(allowed,dict) and all(k in allowed and permits(v,allowed[k]) for k,v in value.items())
    if isinstance(value,list):return isinstance(allowed,list) and all(any(permits(v,a) for a in allowed) for v in value)
    if isinstance(value,str):return isinstance(allowed,str) and fnmatch.fnmatchcase(value,allowed)
    return type(value) is type(allowed) and value==allowed

def extract(ipa,destination):
    with zipfile.ZipFile(ipa) as archive:
        if len(archive.infolist())>100000 or sum(i.file_size for i in archive.infolist())>2*1024**3:
            raise ValueError('Package exceeds extraction limit')
        for item in archive.infolist():
            path=PurePosixPath(item.filename)
            mode=item.external_attr>>16
            if path.is_absolute() or '..' in path.parts or '\\' in item.filename or stat.S_ISLNK(mode):
                raise ValueError('Unsafe package member')
            archive.extract(item,destination)
            target=destination.joinpath(*path.parts)
            if not item.is_dir() and mode&0o777:target.chmod(mode&0o777)

def resign(ipa:Path,new_profile:Path,output:Path,build:int,notes:str)->dict:
    if build<=0 or not notes.strip() or len(notes)>12000:raise ValueError('Invalid build or release notes')
    provision=profile(new_profile)
    if provision.get('TeamIdentifier')!=[TEAM_ID] or provision.get('ProvisionsAllDevices') or not provision.get('ProvisionedDevices'):
        raise ValueError('Expected the configured team Ad Hoc profile')
    if provision['ExpirationDate'].replace(tzinfo=dt.timezone.utc)<=dt.datetime.now(dt.timezone.utc):raise ValueError('Profile expired')
    allowed=provision['Entitlements']
    if not fnmatch.fnmatchcase(TEAM_ID+'.'+BUNDLE_ID,allowed.get('application-identifier','')) or allowed.get('get-task-allow') is not False:
        raise ValueError('Profile identity mismatch')
    valid_certificates={hashlib.sha1(c).hexdigest().upper() for c in provision['DeveloperCertificates']}
    identities=run(['security','find-identity','-v','-p','codesigning']).decode()
    identity=next((fingerprint for fingerprint in valid_certificates if fingerprint in identities),None)
    if not identity:raise ValueError('Profile signing identity is not available in the temporary keychain')
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tongiva-resign-') as temp:
        root=Path(temp);extract(ipa,root)
        apps=list((root/'Payload').glob('*.app'))
        if len(apps)!=1:raise ValueError('Expected one application')
        app=apps[0];info_path=app/'Info.plist';info=plistlib.loads(info_path.read_bytes())
        if info.get('CFBundleIdentifier')!=BUNDLE_ID or int(info['CFBundleVersion'])>=build:raise ValueError('Package identity/build mismatch')
        if list(app.rglob('*.appex')) or [p for p in app.rglob('*.app') if p!=app]:raise ValueError('Nested applications require separate provisioning profiles')
        entitlements=plistlib.loads(run(['codesign','-d','--entitlements',':-',app]))
        if entitlements.get('application-identifier')!=TEAM_ID+'.'+BUNDLE_ID or entitlements.get('get-task-allow') is not False:
            raise ValueError('Original application signing identity mismatch')
        if not permits(entitlements,allowed):raise ValueError('Updated profile does not preserve all existing application entitlements')
        old_entitlements=dict(entitlements)
        info['CFBundleVersion']=str(build)
        info_path.write_bytes(plistlib.dumps(info,fmt=plistlib.FMT_BINARY))
        (app/'embedded.mobileprovision').write_bytes(new_profile.read_bytes())
        entitlement_path=root/'signing-entitlements.plist';entitlement_path.write_bytes(plistlib.dumps(entitlements))
        nested=sorted([*app.rglob('*.framework'),*app.rglob('*.dylib')],key=lambda p:len(p.parts),reverse=True)
        for path in nested:run(['codesign','--force','--sign',identity,path])
        executable=app/info['CFBundleExecutable'];executable.chmod(executable.stat().st_mode|0o111)
        run(['codesign','--force','--sign',identity,'--entitlements',entitlement_path,'--generate-entitlement-der',app])
        run(['codesign','--verify','--deep','--strict',app])
        if plistlib.loads(run(['codesign','-d','--entitlements',':-',app]))!=old_entitlements:raise ValueError('Signing changed application entitlements')
        name=f'Tongiva-iOS-v{build}.ipa';target=output/name
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for path in sorted((root/'Payload').rglob('*')):
                if path.is_file():archive.write(path,path.relative_to(root).as_posix())
    manifest_name=f'Tongiva-iOS-v{build}.plist'
    manifest=plistlib.dumps({'items':[{'assets':[{'kind':'software-package','url':ASSET_ROOT+name}],
        'metadata':{'bundle-identifier':BUNDLE_ID,'bundle-version':str(build),'kind':'software','title':'Tongiva'}}]},sort_keys=False)
    (output/manifest_name).write_bytes(manifest)
    digest=hashlib.sha256()
    with target.open('rb') as package:
        for chunk in iter(lambda:package.read(1048576),b''):digest.update(chunk)
    metadata={'schemaVersion':1,'platform':'ios','bundleIdentifier':BUNDLE_ID,'version':info['CFBundleShortVersionString'],
        'build':build,'minimumOSVersion':info.get('MinimumOSVersion','15.0'),'name':name,'url':ASSET_ROOT+name,
        'size':target.stat().st_size,'sha256':digest.hexdigest(),'manifestURL':ASSET_ROOT+manifest_name,
        'manifestSHA256':hashlib.sha256(manifest).hexdigest(),'releaseNotes':notes.strip(),
        'deviceSetSHA256':device_hash(provision['ProvisionedDevices']),'deviceCount':len(provision['ProvisionedDevices'])}
    (output/'ios-update.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    return metadata

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ipa',type=Path);parser.add_argument('profile',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--build',type=int,required=True);parser.add_argument('--notes-file',type=Path,required=True)
    args=parser.parse_args();result=resign(args.ipa,args.profile,args.output,args.build,args.notes_file.read_text())
    print(json.dumps({'build':result['build'],'devices':result['deviceCount'],'size':result['size'],'signature':'verified'}))
