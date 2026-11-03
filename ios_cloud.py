"""Check registered devices and publish a verified, newly signed iOS release."""
from __future__ import annotations
import argparse,base64,hashlib,json,os,re,signal,subprocess,tempfile,time,urllib.error,urllib.parse,urllib.request
from pathlib import Path
from ios_resign import resign,ASSET_ROOT,BUNDLE_ID
REPO='wgp899-eng/tongiva-releases'
API='https://api.github.com'
FEED=ASSET_ROOT+'ios-update.json'

class GitHubRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,message,headers,url):
        target=urllib.parse.urlsplit(url)
        if target.scheme!='https' or not (target.hostname in ['github.com','api.github.com','uploads.github.com'] or (target.hostname or '').endswith('.githubusercontent.com')):
            raise ValueError('Unexpected GitHub redirect')
        if request.has_header('Authorization') and target.hostname not in ['api.github.com','uploads.github.com']:
            raise ValueError('Credential redirect is not allowed')
        return super().redirect_request(request,fp,code,message,headers,url)
OPEN=urllib.request.build_opener(GitHubRedirects()).open

def read_json(url):
    request=urllib.request.Request(url,headers={'Cache-Control':'no-cache','User-Agent':'Tongiva-Cloud-Publisher'})
    with OPEN(request,timeout=30) as response:data=response.read(1024*1024+1)
    if len(data)>1024*1024:raise ValueError('JSON exceeds limit')
    return json.loads(data)
def metadata():
    value=read_json(FEED+'?check='+str(time.time_ns()))
    build=value.get('build')
    if type(build) is not int or build<=0 or value.get('bundleIdentifier')!=BUNDLE_ID or value.get('platform')!='ios':raise ValueError('Invalid iOS feed')
    if value.get('name')!=f'Tongiva-iOS-v{build}.ipa' or value.get('url')!=ASSET_ROOT+value['name']:raise ValueError('Invalid package source')
    if type(value.get('size')) is not int or value['size']<=0 or not re.fullmatch('[a-f0-9]{64}',value.get('sha256','')):raise ValueError('Invalid package metadata')
    return value

def bridge(command):
    args=['ssh','-i',os.environ['IOS_SSH_KEY_FILE'],'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
          '-o','UserKnownHostsFile='+os.environ['IOS_SSH_KNOWN_HOSTS'],'-o','ConnectTimeout=15','root@154.94.238.221',command]
    result=subprocess.run(args,capture_output=True,check=True,timeout=240)
    if len(result.stdout)>2*1024*1024:raise ValueError('Bridge response exceeds limit')
    return json.loads(result.stdout)

def needed():
    state=bridge('status');current=metadata()
    if not state['needsSigning']:return False,state,current
    if current.get('deviceSetSHA256')==state['registeredDeviceSetSHA256']:
        bridge('refresh');return False,bridge('status'),current
    return True,state,current

def api(method,path,body=None,content_type='application/json'):
    url=path if path.startswith('https://') else API+path
    if urllib.parse.urlsplit(url).hostname not in ['api.github.com','uploads.github.com']:raise ValueError('Invalid GitHub API destination')
    token=os.environ['GITHUB_TOKEN']
    data=json.dumps(body,ensure_ascii=False).encode() if isinstance(body,dict) else body
    request=urllib.request.Request(url,data=data,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
        'Content-Type':content_type,'X-GitHub-Api-Version':'2022-11-28','User-Agent':'Tongiva-Cloud-Publisher'})
    with OPEN(request,timeout=180) as response:value=response.read()
    return json.loads(value) if value else None

def release():return api('GET','/repos/'+REPO+'/releases/tags/ios-updates')
def upload(info,path,name=None):
    name=name or path.name
    existing=next((a for a in info['assets'] if a['name']==name),None)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if existing:
        if existing.get('digest')=='sha256:'+digest:return existing
        raise ValueError('A different asset already uses this versioned name')
    url=info['upload_url'].split('{',1)[0]+'?'+urllib.parse.urlencode({'name':name})
    result=api('POST',url,path.read_bytes(),'application/octet-stream')
    if result.get('digest') and result['digest']!='sha256:'+digest:raise ValueError('Uploaded asset digest mismatch')
    return result

def same_release(value,base):return value['build']==base['build'] and value['sha256']==base['sha256']
def publish(base,new,output):
    info=release()
    if not same_release(metadata(),base):raise ValueError('A newer release was published while signing; rerun against it')
    upload(info,output/new['name']);upload(info,output/f"Tongiva-iOS-v{new['build']}.plist")
    info=release()
    if not same_release(metadata(),base):raise ValueError('Release changed before activating the new feed')
    old=next(a for a in info['assets'] if a['name']=='ios-update.json')
    archive=f"ios-update-v{base['build']}.json"
    if any(a['name']==archive for a in info['assets']):archive=f"ios-update-v{base['build']}-snapshot-{old['id']}.json"
    staged=upload(info,output/'ios-update.json',f"ios-update-next-v{new['build']}.json")
    # All immutable package assets already exist. Keep the old feed as a named
    # archive and restore it if activating the replacement fails; delete nothing.
    moved=False
    try:
        api('PATCH','/repos/'+REPO+'/releases/assets/'+str(old['id']),{'name':archive});moved=True
        api('PATCH','/repos/'+REPO+'/releases/assets/'+str(staged['id']),{'name':'ios-update.json'})
    except BaseException:
        if moved:
            assets=release()['assets']
            if not any(a['name']=='ios-update.json' for a in assets):
                api('PATCH','/repos/'+REPO+'/releases/assets/'+str(old['id']),{'name':'ios-update.json'})
        raise
    observed=None
    for attempt in range(12):
        try:
            observed=metadata()
            if observed['build']==new['build'] and observed['sha256']==new['sha256']:break
        except Exception:pass
        time.sleep(5)
    if not observed or not same_release(observed,new):raise RuntimeError('Published feed verification failed')
    body='iOS 独立更新通道，当前推荐版本 v'+str(new['build'])+'。\n\n'+new['releaseNotes']+'\n\n首次安装和更新使用同一完整包。请保留原应用进行覆盖安装。历史版本保留，本通道不设为仓库 Latest。'
    api('PATCH','/repos/'+REPO+'/releases/'+str(info['id']),{'name':f"Tongiva iOS 更新通道（当前 v{new['build']}）",'body':body,'make_latest':'false'})
    state=bridge('refresh')
    if state['activeBuild']<new['build']:raise RuntimeError('Distribution server has not activated the published release')
    return state

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['check','publish']);args=parser.parse_args()
    required,state,base=needed()
    if args.command=='check':
        output=os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output,'a') as file:file.write('needed='+str(required).lower()+'\n')
        print(json.dumps({'needsSigning':required,'registeredDevices':state['registeredCount'],'activeBuild':state['activeBuild']}));return
    if not required:
        print('All registered devices are already supported; no package changed.');return
    with tempfile.TemporaryDirectory(prefix='tongiva-publish-') as tmp:
        root=Path(tmp);ipa=root/base['name'];digest=hashlib.sha256();received=0
        with OPEN(urllib.request.Request(base['url'],headers={'User-Agent':'Tongiva-Cloud-Publisher'}),timeout=90) as response,ipa.open('wb') as file:
            while chunk:=response.read(1048576):
                received+=len(chunk)
                if received>base['size']:raise ValueError('Source package exceeds advertised size')
                file.write(chunk);digest.update(chunk)
        if received!=base['size'] or digest.hexdigest()!=base['sha256']:raise ValueError('Source package digest mismatch')
        provision=bridge('profile '+state['registeredDeviceSetSHA256'])
        profile_path=root/'current.mobileprovision';profile_path.write_bytes(base64.b64decode(provision['profileBase64'],validate=True));profile_path.chmod(0o600)
        notes=(base.get('releaseNotes') or '保留现有客户端功能，完善设备安装支持。').strip()+'\n更新设备安装支持。'
        reserved=[int(match.group(1)) for asset in release()['assets']
            if (match:=re.fullmatch(r'Tongiva-iOS-v(\d+)\.ipa',asset['name']))]
        next_build=max([base['build'],*reserved])+1
        output=root/'output';new=resign(ipa,profile_path,output,next_build,notes)
        if new['deviceSetSHA256']!=provision['deviceSetSHA256'] or new['deviceCount']!=provision['deviceCount']:raise ValueError('Signed package contains a different device list')
        final=publish(base,new,output)
        print(json.dumps({'publishedBuild':new['build'],'signedDevices':new['deviceCount'],'serverBuild':final['activeBuild'],'remainingNewDevices':final['missingDeviceCount']}))

if __name__=='__main__':
    signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
    try:main()
    except Exception as error:
        print('Cloud iOS publication failed: '+type(error).__name__,file=__import__('sys').stderr)
        raise SystemExit(1)
