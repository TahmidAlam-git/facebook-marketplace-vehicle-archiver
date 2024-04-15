# Standard libraries
import re
import json
import requests
import datetime
from io import BytesIO

# Third party libraries
import yaml
from bs4 import BeautifulSoup
from tinydb import TinyDB, Query
from internetarchive import upload
from playwright.sync_api import sync_playwright

# Fast API related libraries
import uvicorn
from pydantic import BaseModel
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Constants
BASE_URL = 'https://www.facebook.com'
BASE_MARKETPLACE_URL = BASE_URL + '/marketplace/item/'

# Global
db = TinyDB('db.json')
app = FastAPI()

# Load the settings file
with open('settings.yml', 'r') as file:
    settings = yaml.safe_load(file)

# What is allowed to interface this backend (currently everything)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Item to recieve from post request
class Item(BaseModel, extra="allow"):
    payload: list[dict]

# Temporary base path for API 
@app.get('/')
def root():
    return {'message': 'temporary root message'}

# login to Facebook
def login(page):
    page.goto(f'{BASE_URL}/login/device-based/regular/login/')
    page.wait_for_selector('input[name="email"]').fill(settings['email'])
    page.wait_for_selector('input[name="pass"]').fill(settings['password'])
    page.wait_for_selector('button[name="login"]').click()

    # There is a bug in playwright, have to manually wait 
    # till it's fixed: https://github.com/microsoft/playwright-python/issues/2238
    # page.wait_for_url(BASE_URL)
    page.wait_for_timeout(30000)

# Scroll to the bottom of an infinite scroll by checking if the page  
# height has changed after scrolling
def scroll_to_bottom(page):
    js_page_height_code = '(window.innerHeight + window.scrollY)'
    prev_height = 0
    while prev_height != page.evaluate(js_page_height_code):
        prev_height = page.evaluate(js_page_height_code)
        page.mouse.wheel(0, 150000)
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

# Get the HTML element text, if not found return empty string
def soup_find(soup: BeautifulSoup, type: str, class_name: str, default=''):
    if soup == None:
        return ''
    res = soup.find(type, class_=class_name)
    return res.text if (res != None) else default

# Find all posts 
def get_matching_posts(page):
    parsed = []
    soup = BeautifulSoup(page.content(), 'html.parser')

    # Iterate through all the listings and keep the ones that match the criteria
    listings = soup.find_all('div', 
                             class_=('x9f619 x78zum5 x1r8uery xdt5ytf '
                                     'x1iyjqo2 xs83m0k x1e558r4 x150jy0e '
                                     'x1iorvi4 xjkvuk6 xnpuxes x291uyu '
                                     'x1uepa24'))
    for listing in listings:
        try:
            image = listing.find('img', 
                                 class_=('xt7dq6l xl1xv1r x6ikm8r x10wlt62 '
                                         'xh8yej3'))['src']
            title = listing.find('span', 
                                 'x1lliihq x6ikm8r x10wlt62 x1n2onr6').text
            price = listing.find_all('span', 
                                 ('x193iq5w xeuugli x13faqbe x1vvkbs '
                                  'x1xmvt09 x1lliihq x1s928wv xhkezso '
                                  'x1gmr53x x1cpjm7i x1fgarty x1943h6x '
                                  'xudqn12 x676frb x1lkfr7t x1lbecb7 '
                                  'x1s688f xzsf02u'))[-1].text
            post_url = listing.find('a', 
                                    class_=('x1i10hfl xjbqb8w x1ejq31n xd10rxx '
                                            'x1sy0etr x17r0tee x972fbf xcfux6l '
                                            'x1qhh985 xm0m39n x9f619 x1ypdohk '
                                            'xt0psk2 xe8uvvx xdj266r x11i5rnm '
                                            'xat24cr x1mh8g0r xexx8yu x4uap5 '
                                            'x18d9i69 xkhd6sd x16tdsg8 x1hl2dhg '
                                            'xggy1nq x1a2a7pz x1heor9g x1lku1pv'))['href']
            location = listing.find('span', 
                                    ('x1lliihq x6ikm8r x10wlt62 x1n2onr6 '
                                     'xlyipyv xuxw1ft x1j85h84')).text
            
            # keep the posts that match
            if (
                all(string.lower() in title.lower() for string in settings['must-contain']) and
                all(string.lower() not in title.lower() for string in settings['dont-contain']) and 
                db.search(Query()['identity'] == re.search(r'marketplace\/item\/(\d+)', post_url).group(1)) == []
            ):
                parsed.append({
                    'image': image,
                    'title': title,
                    'price': price,
                    'post_url': post_url,
                    'location': location
                })

        except Exception as e:
            print("something went wrong with extracting data from the listing:", e)

    return parsed

# Mark posts that appear real or fake
def pre_filter(posts):
    for post in posts:
        price = re.sub("[^0-9]", "", post['price'])
        # TODO: make this price range adjustable via settings
        if price == '' or int(price) <= 1234 or int(price) >= 100000:
            post['real'] = False
        else:
            post['real'] = True

# Iterate through all location pages and find all vehicles
@app.get("/scrape")
def get_basic_listings():
    """ with open('sample3.json', 'r') as file:
        return json.load(file) """

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        login(page)

        posts = []
        for location in settings['locations']:
            for status in ['', 'availability=out of stock&']:
                
                # Go to the search page
                page.goto((f"{BASE_URL}/marketplace/{location}/search?{status}daysSinceListed={settings['days-since-listed']}&sortBy={settings['sort-by']}&query={settings['vehicle']}&exact=false&radius=805"))
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(3000)

                # Load all the results
                scroll_to_bottom(page)
                page.wait_for_load_state("networkidle")

                # Get the results
                posts.extend(get_matching_posts(page))
        pre_filter(posts)

        # print results
        for x, post in enumerate(posts):
            print(x, post)
        print('count', len(posts))

        return posts

# Return dict with all post details
# Return None if invalid post
def get_post_details(page):
    if 'unavailable_product' in page.url:
        return None

    result = {'url': '', 
              'title': '', 
              'sold': False, 
              'year': '', 
              'price': '', 
              'date': '', 
              'location': '', 
              'mileage': '', 
              'color': '', 
              'seller': '', 
              'description': '', 
              'images': []}

    # Open the full description
    description_button = page.get_by_role("button", name="See more")
    if description_button.is_visible():
        description_button.click()
        page.wait_for_timeout(500)

    soup = BeautifulSoup(page.content(), 'html.parser')

    # get url
    url = re.search(r'(.*\/marketplace\/item\/(\d+))', page.url).group(1)
    result['url'] = url

    # Get description
    result['description'] = soup_find(soup, 
                                      'div', 
                                      ('xz9dl7a x4uap5 xsag5q8 xkhd6sd '
                                       'x126k92a'))

    # Get full title
    header = soup.find('div', class_='xyamay9 x1pi30zi x18d9i69 x1swvt13')
    result['title'] = soup_find(header, 
                                'span', 
                                ('x193iq5w xeuugli x13faqbe x1vvkbs '
                                 'x1xmvt09 x1lliihq x1s928wv xhkezso '
                                 'x1gmr53x x1cpjm7i x1fgarty x1943h6x '
                                 'x14z4hjw x3x7a5m xngnso2 x1qb5hxa '
                                 'x1xlr1w8 xzsf02u'))

    # Get model year
    year = re.search(r'(\d\d\d\d)', result['title'])
    result['year'] = year.group(1) if year else ''

    # Sold status
    result['sold'] = ('sold' in result['title'].lower() or 
                      'pending' in result['title'].lower() or 
                      'out of stock' in result['title'].lower())

    # Get short title
    title = re.search(r'(?:.*? · )?(.*)', result['title'])
    result['title'] = title.group(1) if year else ''

    # Get price
    result['price'] = soup_find(header, 
                                'span', 
                                ('x193iq5w xeuugli x13faqbe x1vvkbs '
                                 'x1xmvt09 x1lliihq x1s928wv xhkezso '
                                 'x1gmr53x x1cpjm7i x1fgarty x1943h6x '
                                 'xudqn12 x676frb x1lkfr7t x1lbecb7 '
                                 'x1s688f xzsf02u'))
    
    # Get price backup (regular post)
    if result['price'] == '':
        price = soup_find(header, 
                          'span', 
                          ('x193iq5w xeuugli x13faqbe x1vvkbs '
                           'x1xmvt09 x1lliihq x1s928wv xhkezso '
                           'x1gmr53x x1cpjm7i x1fgarty x1943h6x '
                           'xudqn12 x676frb x1lkfr7t x1lbecb7 '
                           'xk50ysn xzsf02u'))
        price = re.search(r'\$(\d+(,\d+)?)', price) # up to 999,999
        result['price'] = price.group(1) if price else ''

    # get date
    result['date'] = soup_find(header, 
                               'span', 
                               ('html-span xdj266r x11i5rnm xat24cr x1mh8g0r '
                                'xexx8yu x4uap5 x18d9i69 xkhd6sd '
                                'x1hl2dhg x16tdsg8 x1vvkbs'), 
                                'a minute ago')
    date_search = re.search(r'(a|an|\d+) (hour|day|week|minute)', result['date'])
    value = 1 if date_search.group(1).isalpha() else date_search.group(1)
    unit = date_search.group(2)
    if unit == 'minute':
        result['date'] = (datetime.datetime.now() - 
                            datetime.timedelta(minutes=int(value)))
    elif unit == 'hour':
        result['date'] = (datetime.datetime.now() - 
                            datetime.timedelta(hours=int(value)))
    elif unit == 'day':
        result['date'] = (datetime.datetime.now() - 
                            datetime.timedelta(days=int(value)))
    elif unit == 'week':
        result['date'] = (datetime.datetime.now() - 
                            datetime.timedelta(weeks=int(value)))
    result['date'] = result['date'].strftime("%Y-%m-%d")

    # get location
    result['location'] = soup_find(header, 
                                   'span', 
                                   ('x193iq5w xeuugli x13faqbe x1vvkbs '
                                    'x1xmvt09 x1nxh6w3 x1sibtaa xo1l8bm '
                                    'xi81zsa'))

    # Get all vehicle detail spans
    spans = soup.find_all('span', 
                          class_=('x193iq5w xeuugli x13faqbe x1vvkbs '
                                  'x1xmvt09 x1lliihq x1s928wv xhkezso '
                                  'x1gmr53x x1cpjm7i x1fgarty x1943h6x '
                                  'xudqn12 x3x7a5m x6prxxf xvq8zen '
                                  'xo1l8bm xzsf02u'))
    if len(spans) > 0:
        # get mileage
        mileage = [span for span in spans if 'Driven' in span.text]
        mileage = mileage[0].text if len(mileage) > 0 else ''
        mileage = re.search(r'Driven (\d+(,\d+)?) miles', mileage)
        result['mileage'] = mileage.group(1) if mileage else ''

        # get color
        color = [span for span in spans if 'color' in span.text]
        color = color[0].text if len(color) > 0 else ''
        color = re.search(r'Exterior color: (\w+) ?\w*', color)
        result['color'] = color.group(1) if color else 'unknown'

    # get seller name
    header = soup.find('div', class_='x1lq5wgf xgqcy7u x30kzoy x9jhf4c x1lliihq')
    if header:
        result['seller'] = soup_find(header, 
                                     'span', 
                                     ('x193iq5w xeuugli x13faqbe x1vvkbs '
                                      'x1xmvt09 x6prxxf xvq8zen x1s688f '
                                      'xzsf02u'))

    # get images
    image_roll = soup.find('div', class_=('x6s0dn4 x78zum5 x193iq5w x1y1aw1k '
                                          'xwib8y2 xu6gjpd x11xpdln x1r7x56h '
                                          'xuxw1ft xc9qbxq'))
    
    # If there is a image roll
    if image_roll:
        result['images'] = [image['src'] for image in image_roll.find_all('img', class_='x5yr21d xl1xv1r xh8yej3')]
    # Else there is a single image
    else:
        image = soup.find('img', class_='xz74otr')
        result['images'] = [image['src']] if image else []

    return result

# Upload the post details and images to internet archive
def upload_to_internet_archive(listing: dict):

    long_url_search = re.search(r'(.*\/marketplace\/item\/(\d+))', listing['url'])
    short_url = long_url_search.group(1)
    listing_identifier = long_url_search.group(2)

    images = [(str(i) + '.jpg', 
               BytesIO(requests.get(url, stream=True).content)) 
               for i, url in enumerate(listing['images'])]

    # Main meta data for internet archive
    meta_data = {
        'mediatype': 'image',
        'subject': settings['vehicle'],
        'title': 'FB Marketplace ' + listing_identifier + ' - ' + listing['title'],
        'date': listing['date'],
        'source': short_url
    }

    # extra meta data for listing
    for key in listing.keys():
        if key not in {'images', 'url', 'title'}:
            meta_data[key] = str(listing[key])

    print('uploading...')
    try:
        # if uploading all images is successful update the db
        upload_result = upload(identifier=('facebook-marketplace-item-' + listing_identifier), 
                               files=images, 
                               metadata=meta_data, 
                               access_key=settings['access-key'], 
                               secret_key=settings['secret-key'])
        
        if all(result.status_code == 200 for result in upload_result):
            db.update({'archived': True}, (Query()['identity'] == listing_identifier))
            print('db updated')

        return {'link': 'https://archive.org/details/facebook-marketplace-item-' + listing_identifier, 
                'result': 'success'}
    
    except Exception as e:
        print('Archiving error:', e)
        return {'link': 'None', 
                'result': 'fail'}

# Get post details and save them to profile/db/archiving platform
@app.post("/archive")
def archive_listings(item: Item):

    output = ''

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        login(page)

        for listing in item.payload:
            if not listing['real']:
                continue

            # go to the listing page
            page.goto(f"{BASE_URL}{listing['post_url']}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)

            # save the listing if not already saved
            button = page.get_by_role('button', name="Save", pressed=False)
            button_visible = button.is_visible()

            if settings['save-to-profile']:
                if button_visible:
                    button.click()
                    print('Saved', listing['post_url'])
                else:
                    print('Already saved', listing['post_url'])
            else:
                print('Skipping save', listing['post_url'])
            
            post = get_post_details(page)
            print(post)

            # save the post in the db
            if post != None:
                identity = re.search(r'marketplace\/item\/(\d+)', post['url']).group(1)                
                db.upsert({'identity': identity,
                           'archived': False,
                           'details': post},
                           (Query()['identity'] == identity))
                print(identity, 'saved to db')
            else:
                print('Invalid post, did not save to db')
                
        browser.close()

    # get all entries that aren't archived
    if settings['save-to-internet-archive']:
        for entry in db.search(Query()['archived'] == False):
            post = entry['details']
            upload_result = upload_to_internet_archive(post)
            print('upload result:', upload_result['result'])

            # add your own custom_output.py file with the function
            # 'def custom_output()' to make your own output
            try:
                from custom_output import custom_output
                output += "REMOVE " + custom_output(post, upload_result['link']) + "\n"
            except:
                pass
    else:
        output = 'Archiving skipped'
    
    print(output)
    return {'response': output}

if __name__ == '__main__':
    uvicorn.run('app:app', 
                host='127.0.0.1', 
                port=8000)