import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import time
import pathlib
import zipfile
import io
import datetime
import json
from datetime import timedelta

class GujaratSamacharScraper:
    def __init__(self):
        self.BASE = "https://epaper.gujaratsamachar.com"
        self.EDITION = "ahmedabad"
        self.HEADERS = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }

    def page_url(self, date, pg):
        return f"{self.BASE}/view_article/{self.EDITION}/{date}/{pg}"

    def article_url(self, date, pg, artid):
        return f"{self.BASE}/view_article/{self.EDITION}/{date}/{pg}/{artid}"

    def fetch(self, url, sess):
        r = sess.get(url, headers=self.HEADERS, allow_redirects=True, timeout=10)
        r.raise_for_status()
        return r

    def get_first_article_id(self, date, page, sess):
        """Visit the page URL and get redirected to first article"""
        try:
            # First visit the page URL
            page_url = self.page_url(date, page)
            response = self.fetch(page_url, sess)

            # Extract article ID from the redirected URL
            match = re.search(r'/(\d+)$', response.url)
            if match:
                return int(match.group(1)), response.text
            else:
                raise ValueError(f"Could not find article ID in URL: {response.url}")

        except Exception as e:
            st.error(f"Error getting first article ID for page {page}: {str(e)}")
            return None, None

    def get_article_image(self, html_text):
        """Extract the main article image using the current_artical ID"""
        soup = BeautifulSoup(html_text, "html.parser")
        img_tag = soup.find('img', id='current_artical')
        if img_tag and 'src' in img_tag.attrs:
            src = img_tag['src']
            return src if src.startswith("http") else self.BASE + src
        return None

    def get_article_metadata(self, soup):
        """Extract article metadata"""
        metadata = {}
        try:
            title_elem = soup.find('div', class_='article_title')
            if title_elem:
                metadata['title'] = title_elem.get_text(strip=True)

            content_elem = soup.find('div', class_='article_text')
            if content_elem:
                metadata['content'] = content_elem.get_text(strip=True)
        except Exception as e:
            st.warning(f"Error extracting metadata: {e}")
        return metadata

    def scrape_page(self, date, pg, sess, status_placeholder, stats_placeholder, metadata_dict):
        images = []
        start_time = time.time()

        try:
            # Get the first article ID for this page
            first_artid, first_html = self.get_first_article_id(date, pg, sess)
            if not first_artid:
                return [], 0, 0

            articles_searched = 0
            images_found = 0
            current_artid = first_artid
            seen_articles = set([first_artid])  # Keep track of articles we've seen

            # Process the first article
            img_url = self.get_article_image(first_html)
            if img_url:
                img_response = self.fetch(img_url, sess)
                if img_response.status_code == 200:
                    filename = f"{date}_{pg}_{current_artid}.jpeg"
                    images.append((filename, img_response.content))
                    images_found += 1

                    # Get and store metadata
                    metadata = self.get_article_metadata(BeautifulSoup(first_html, 'html.parser'))
                    metadata['url'] = self.article_url(date, pg, current_artid)
                    metadata['image_filename'] = filename
                    metadata_dict[f"{pg}_{current_artid}"] = metadata

            # Continue with next articles
            while True:
                current_artid += 1
                articles_searched += 1

                url = self.article_url(date, pg, current_artid)
                try:
                    r = self.fetch(url, sess)
                    soup = BeautifulSoup(r.text, 'html.parser')

                    # Check if we've seen this article before
                    article_content = soup.find('div', class_='article_text')
                    if article_content:
                        content_hash = hash(article_content.get_text(strip=True))
                        if content_hash in seen_articles:
                            st.write(f"Found duplicate article on page {pg}, moving to next page")
                            break
                        seen_articles.add(content_hash)

                    # Get the main article image
                    img_url = self.get_article_image(r.text)
                    if img_url:
                        img_response = self.fetch(img_url, sess)
                        if img_response.status_code == 200:
                            filename = f"{date}_{pg}_{current_artid}.jpeg"
                            images.append((filename, img_response.content))
                            images_found += 1

                            # Get and store metadata
                            metadata = self.get_article_metadata(soup)
                            metadata['url'] = url
                            metadata['image_filename'] = filename
                            metadata_dict[f"{pg}_{current_artid}"] = metadata

                    # Update status
                    status_placeholder.text(
                        f"""
                        📄 Current Status:
                        Page: {pg}
                        Current Article ID: {current_artid}
                        Articles Searched: {articles_searched}
                        Images Found: {images_found}
                        """
                    )

                    # Update statistics
                    stats_placeholder.text(
                        f"""
                        📊 Page Statistics:
                        Success Rate: {(images_found/articles_searched*100):.1f}%
                        Average Time per Article: {(time.time() - start_time)/articles_searched:.2f}s
                        """
                    )

                except requests.HTTPError as e:
                    if e.response.status_code == 404:
                        # If we hit too many 404s, assume we've reached the end
                        if articles_searched > 100:  # Safeguard against infinite loops
                            break
                    else:
                        raise

                time.sleep(0.6)  # Polite delay

        except Exception as e:
            st.error(f"Error scraping page {pg}: {str(e)}")

        return images, articles_searched, images_found

    def create_zip(self, images, metadata_dict):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Add images
            for filename, content in images:
                zip_file.writestr(f"images/{filename}", content)

            # Add metadata as JSON
            zip_file.writestr("metadata.json", json.dumps(metadata_dict, indent=4, ensure_ascii=False))

        return zip_buffer

def main():
    st.set_page_config(page_title="Gujarat Samachar Scraper", layout="wide")
    st.title("Gujarat Samachar E-Paper Scraper")

    # Date selector
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_date = st.date_input(
            "Select Date",
            value=datetime.date.today(),
            min_value=datetime.date.today() - timedelta(days=30),
            max_value=datetime.date.today()
        )
    with col2:
        num_pages = st.number_input("Number of Pages to Scrape",
                                  min_value=1,
                                  max_value=30,
                                  value=5)

    if st.button("Start Scraping"):
        date_str = selected_date.strftime('%d-%m-%Y')
        scraper = GujaratSamacharScraper()
        all_images = []
        metadata_dict = {}

        # Create containers for status updates
        progress_bar = st.progress(0)
        col1, col2 = st.columns(2)

        with col1:
            status_placeholder = st.empty()
        with col2:
            stats_placeholder = st.empty()

        overall_stats = {
            'total_articles_searched': 0,
            'total_images_found': 0,
            'failed_pages': []
        }

        # Summary metrics containers
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

        try:
            with requests.Session() as sess:
                sess.headers.update(scraper.HEADERS)

                for page in range(1, num_pages + 1):
                    st.write(f"### Processing Page {page}")

                    images, articles_searched, images_found = scraper.scrape_page(
                        date_str, page, sess,
                        status_placeholder, stats_placeholder,
                        metadata_dict
                    )

                    all_images.extend(images)
                    overall_stats['total_articles_searched'] += articles_searched
                    overall_stats['total_images_found'] += images_found

                    # Update progress
                    progress_bar.progress(page / num_pages)

                    # Update metrics
                    with metric_col1:
                        st.metric("Pages Completed", page)
                    with metric_col2:
                        st.metric("Total Articles Searched", overall_stats['total_articles_searched'])
                    with metric_col3:
                        st.metric("Total Images Found", overall_stats['total_images_found'])
                    with metric_col4:
                        success_rate = (overall_stats['total_images_found'] /
                                      overall_stats['total_articles_searched'] * 100
                                      if overall_stats['total_articles_searched'] > 0 else 0)
                        st.metric("Overall Success Rate", f"{success_rate:.1f}%")

            if all_images:
                # Create zip file with images and metadata
                zip_buffer = scraper.create_zip(all_images, metadata_dict)

                # Offer download
                st.download_button(
                    label="📥 Download ZIP file",
                    data=zip_buffer.getvalue(),
                    file_name=f"gujarat_samachar_{date_str}.zip",
                    mime="application/zip"
                )

                # Display metadata summary
                st.write("### Metadata Summary")
                st.json(metadata_dict)

            else:
                st.warning("No images were found for the selected date and pages.")

        except Exception as e:
            st.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()
