import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import time
import pathlib
import zipfile
import io
import datetime
from datetime import timedelta

class GujaratSamacharScraper:
    def __init__(self):
        self.BASE = "https://epaper.gujaratsamachar.com"
        self.EDITION = "ahmedabad"
        self.HEADERS = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }

    def page_url(self, date, pg):
        return f"{self.BASE}/view_article/{self.EDITION}/{date}/{pg}"

    def article_url(self, date, pg, artid):
        return f"{self.BASE}/view_article/{self.EDITION}/{date}/{pg}/{artid}"

    def fetch(self, url, sess):
        r = sess.get(url, allow_redirects=True, timeout=10)
        r.raise_for_status()
        return r

    def first_article_id(self, date, page, sess):
        r = self.fetch(self.page_url(date, page), sess)
        m = re.search(r"/(\d+)$", r.url)
        if not m:
            raise RuntimeError("Cannot determine first article id")
        return int(m.group(1)), r.text

    def get_article_image(self, html_text):
        """Extract the main article image using the current_artical ID"""
        soup = BeautifulSoup(html_text, "lxml")
        img_tag = soup.find('img', id='current_artical')
        if img_tag and 'src' in img_tag.attrs:
            src = img_tag['src']
            return src if src.startswith("http") else self.BASE + src
        return None

    def scrape_page(self, date, pg, sess, status_container, stats):
        images = []
        try:
            artid, html_text = self.first_article_id(date, pg, sess)
            consecutive_misses = 0
            articles_searched = 0

            # Update starting article ID
            stats['current_article_id'] = artid

            while consecutive_misses < 100:
                url = self.article_url(date, pg, artid)
                try:
                    r = self.fetch(url, sess)
                    consecutive_misses = 0

                    # Get the main article image
                    img_url = self.get_article_image(r.text)
                    if img_url:
                        # Download image
                        img_response = self.fetch(img_url, sess)
                        if img_response.status_code == 200:
                            filename = f"{date}_{pg}_{artid}.jpeg"
                            images.append((filename, img_response.content))
                            stats['total_images'] += 1

                            # Update status
                            status_container.text(
                                f"📄 Page: {pg}\n"
                                f"🔍 Current Article ID: {artid}\n"
                                f"📊 Articles Searched: {articles_searched}\n"
                                f"🎯 Images Found: {stats['total_images']}\n"
                                f"❌ Consecutive Misses: {consecutive_misses}"
                            )

                except requests.HTTPError as e:
                    if e.response.status_code == 404:
                        consecutive_misses += 1
                    else:
                        raise

                artid += 1
                articles_searched += 1
                stats['total_articles_searched'] += 1
                time.sleep(0.6)

            # Page completed successfully
            stats['pages_completed'] += 1

        except Exception as e:
            st.error(f"Error scraping page {pg}: {str(e)}")
            stats['failed_pages'].append(pg)

        return images

    def create_zip(self, images):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for filename, content in images:
                zip_file.writestr(filename, content)
        return zip_buffer
