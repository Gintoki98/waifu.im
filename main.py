import os
import json
import random
import asyncio
import aiomysql
import itsdangerous
from itsdangerous import URLSafeSerializer, BadSignature
import quart
import aiomysql
import functools
from quart import Quart,jsonify,request,current_app
from werkzeug.exceptions import HTTPException
from discord.ext import tasks
import copy

loop=asyncio.get_event_loop()
app = Quart(__name__)

with open("json/credentials.json",'r') as f:
    dt=json.load(f)
    db_user=dt['db_user']
    db_password=dt['db_password']
    db_ip=dt['db_ip']
    db_name=dt['db_name']
    app.secret_key=dt['secret_key']


app.pool=None
app.config['JSON_SORT_KEYS'] = False


"""tools"""

@tasks.loop(minutes=30)
async def get_db():
    loop=asyncio.get_event_loop()
    if app.pool:
        await app.pool.clear()
    else:
        app.pool = await aiomysql.create_pool(user=db_user,password=db_password,host=db_ip,db=db_name,connect_timeout=10,loop=loop,autocommit=True)


def convert_bool(string):
    string=string.lower()
    try:
        string=json.loads(string)
    except:
        return None
    return string
def methodandimage(method,image,user_id):
    image=image.lower()
    try:
        image=[os.path.splitext(x)[0] for x in image.split(",")]
        args=[(user_id,im) for im in image]
    except IndexError:
        return None,None
    if method.lower()=='insert':
        return "INSERT IGNORE INTO FavImages(user_id,image) VALUES(%s,%s)",args
    elif method.lower()=='delete':
        return "DELETE FROM FavImages WHERE user_id=%s and image=%s",args
    return None,None

async def is_valid_token(token_header):
    try:
        token = token_header.split(" ")[1]
        rule = URLSafeSerializer(app.secret_key)
        info=rule.loads(token)
        user_secret=info["secret"]
        user_id=int(info['id'])
    except (TypeError,KeyError,AttributeError,IndexError,BadSignature):
        quart.abort(401,description="Invalid Token, please check that your token is up to date or that you did correctly format it in the Authorization header.")

    else:
        async with app.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id from User WHERE id=%s and secret=%s ",(user_id,user_secret))
                authorized=await cur.fetchone()
                if authorized:
                    return True
                else:
                    quart.abort(401,description="Invalid Token, please check that your token is up to date or that you did correctly format it in the Authorization header.")

"""error handlers"""



@app.errorhandler(HTTPException)
def handle_exception(e):
    response = e.get_response()
    response.data = json.dumps({
        "code": e.code,
        "name": e.name,
        "error": e.description,
    })
    response.content_type = "application/json"
    return response

def requires_token_authorization(view):
    """A decorator for quart views which return a 401 if token is invalid"""

    @functools.wraps(view)
    async def wrapper(*args, **kwargs):
        await is_valid_token(request.headers.get('Authorization'))
        return await view(*args, **kwargs)
    return wrapper

    
async def myendpoints(over18=None):
    async with app.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name,is_over18 FROM Tags")
            rt=await cur.fetchall()
    
    if over18 is None:
        return {"sfw":[tag[0] for tag in rt if not tag[1] and tag[0]!="example"],"nsfw":[tag[0] for tag in rt if tag[1]],'example':'https://api.hori.ovh/sfw/waifu/'}
    elif over18:
        return [tag[0] for tag in rt if tag[1]]
    else:
        return [tag[0] for tag in rt if not tag[1]]


async def myendpoints_info(over18=None):
    async with app.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name,id,is_over18,description FROM Tags")
            rt=await cur.fetchall()

    if over18 is None:
        return {"sfw":[{'name':tag[0],'id':tag[1],'description':tag[3]} for tag in rt if not tag[2] and tag[0]!="example"],"nsfw":[{'name':tag[0],'id':tag[1],'description':tag[3]} for tag in rt if tag[2]],'example':'https://api.hori.ovh/sfw/waifu/'}
    elif over18:
        return [{'name':tag[0],'id':tag[1],'description':tag[3]} for tag in rt if tag[2]]
    else:
        return [{'name':tag[0],'id':tag[1],'description':tag[3]} for tag in rt if not tag[2]]

"""Routes"""
@app.route("/<typ>/<categorie>/")
async def principal(typ,categorie):
    gif=request.args.get('gif')
    banned_files=request.args.get("filter")
    many=request.args.get("many")
    autho=["nsfw","sfw"]
    typ=typ.lower()
    category_is_int=False
    

    if gif:
        gif=convert_bool(gif)
    if many:
        many=convert_bool(many) 
    if banned_files:
        banned_files=[os.path.splitext(x)[0] for x in banned_files.split(",")]
    if typ=="nsfw":
        over18=True
    else:
        over18=False

    try:
        categorie=int(categorie)
        category_is_int=True
    except:
        categorie=categorie.lower()

    if typ in autho:        
        async with app.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if gif==None:
                    gifstr=""
                elif gif:
                    gifstr=" and Images.extension='.gif'"
                else:
                    gifstr=" and not Images.extension='.gif'"
                if category_is_int:
                    strcategory="Tags.id=%s"
                else:
                    strcategory="Tags.name=%s"
                if banned_files:
                    await cur.execute(f"""SELECT Images.file,Images.extension,Tags.id,Tags.name FROM LinkedTags
                                    JOIN Images ON Images.file=LinkedTags.image
                                    JOIN Tags ON Tags.id=LinkedTags.tag_id
                                    WHERE not Images.is_banned and not Images.under_review and {strcategory} and Tags.is_over18={1 if over18 else 0}{gifstr} and LinkedTags.image not in %s{' GROUP BY LinkedTags.image' if many else ''}
                                    ORDER BY RAND() LIMIT {'30' if many else '1'}""",(categorie,banned_files))
                else:
                    await cur.execute(f"""SELECT Images.file,Images.extension,Tags.id,Tags.name FROM LinkedTags
                                    JOIN Images ON Images.file=LinkedTags.image
                                    JOIN Tags ON Tags.id=LinkedTags.tag_id
                                    WHERE not Images.is_banned and not Images.under_review and {strcategory} and Tags.is_over18={1 if over18 else 0}{gifstr}{' GROUP BY LinkedTags.image' if many else ''}
                                    ORDER BY RAND() LIMIT {'30' if many else '1'}""",categorie)

                fetch=list(await cur.fetchall())
                file=[]
                picture=[]
                for im in fetch:
                    file.append(im["file"]+im["extension"])
                    picture.append("https://api.hori.ovh/image/"+im["file"]+im["extension"])
                if len(picture)<1:
                    print(f"This request for {categorie} ended in criteria error.")
                    quart.abort(404,description="No ressources found.")
                tag_id=fetch[0]['id']
                tag_name=fetch[0]['name']

                data={'code':200,'is_over18':over18,'tag_id':tag_id,'tag_name':tag_name,'file':file if len(file)>1 else file[0],'url':picture if len(picture)>1 else picture[0]}
                return jsonify(data)

    return quart.abort(404)

@app.route('/fav/')
@requires_token_authorization
async def fav_():
    token_header = request.headers.get('Authorization')
    token = token_header.split(" ")[1]
    rule = URLSafeSerializer(app.secret_key)
    info=rule.loads(token)
    user_secret=info["secret"]
    user_id=int(info['id'])
    #add or remove image part
    querys=[]
    insert=request.args.get('insert')
    delete=request.args.get('delete')
    if insert:
        querys.append(methodandimage('insert',insert,user_id))
    if delete:
        querys.append(methodandimage('delete',delete,user_id))
    async with app.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            for query in querys:
                await cur.executemany(query[0],query[1])
            await cur.execute("""SELECT Images.extension,Tags.name,Tags.id,Tags.is_over18,Tags.description,Images.file FROM FavImages
                                JOIN Images ON Images.file=FavImages.image
                                JOIN LinkedTags ON LinkedTags.image=FavImages.image
                                JOIN Tags on LinkedTags.tag_id=Tags.id
                                WHERE not Images.is_banned
                                and user_id=%s""",user_id)
            images=await cur.fetchall()
    if not images:
        quart.abort(404,description="You have no Gallery or it is now empty.")
    all_u=[]
    all_f=[]
    tags_nsfw={}
    tags_sfw={}
    default_tags={'ero':tags_nsfw,'all':tags_sfw}
    for im in images:
        filename=im['file']+im["extension"]
        url=f"https://api.hori.ovh/image/{filename}"
        if not im["is_over18"]:
            if not im["name"] in tags_sfw:
                newtag=copy.deepcopy(im)
                del newtag['extension']
                newtag['file']=[]
                newtag['is_over18']=True if newtag['is_over18'] else False
                newtag.update({'url':[]})
                tags_sfw[im["name"]]=newtag
            tags_sfw[im["name"]]['url'].append(url)
            tags_sfw[im["name"]]['file'].append(filename)
        else:
            if not im["name"] in tags_nsfw:
                newtag=copy.deepcopy(im)
                del newtag['extension']
                newtag['file']=[]
                newtag['is_over18']=True if newtag['is_over18'] else False
                newtag.update({'url':[]})
                tags_sfw[im["name"]]=newtag
            tags_nsfw[im["name"]]['url'].append(url)
            tags_nsfw[im["name"]]['file'].append(filename)

    files={}
    if tags_sfw:
        all_f.extend(tags_sfw['all']['file'])
        all_u.extend(tags_sfw['all']['url'])
        files.update({'sfw':tags_sfw})
    if tags_nsfw:
        all_f.extend(tags_sfw['all']['file'])
        all_u.extend(tags_sfw['all']['url'])
        files.update({'nsfw':tags_nsfw})
    if all_f and all_u:
        files.update({'file':all_f,'url':all_u})
    return jsonify(files)

"""endpoints with and without info"""
@app.route('/endpoints_info/')
async def endpoints_info():
    return jsonify(await myendpoints_info(over18=None))

@app.route('/endpoints/')
async def endpoints_():
    return jsonify(await myendpoints(over18=None))

@app.route('/favicon.ico/')
async def favicon():
    return quart.wrappers.response.FileBody("/var/www/virtual_hosts/pics.hori.ovh/favicon/hori_final.ico")

if __name__ == "__main__":
    get_db.start()
    loop.run_until_complete(app.run_task(port=8034))
