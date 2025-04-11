import streamlit as st
import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urlparse
import re
from datetime import datetime
import time
import json
import pandas as pd
from PIL import Image
import io
import zipfile
import tempfile
import shutil
import base64

class NewspaperScraper:
    def __init__(self, date_str, temp_dir):
        self.date_str = date_str
        self.temp_dir = temp_dir
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.base_folder = os.path.join(temp_dir, 'gujarat_samachar_images')
        self.log_file = os.path.join(temp_dir, 'scraping_log.json')
        self.metadata_file = os.path.join(temp_dir, 'article_metadata.json')
        self.consecutive_failures = 0
        self.max_consecutive_failures = 10

        # Create base folder if it doesn't exist
        os.makedirs(self.base_folder, exist_ok=True)

        # Initialize logs and metadata
        self.successful_urls = self.load_log()
        self.metadata = self.load_metadata()

    def load_log(self):
        """Load or create the log file"""
        default_log = {
            'successful_urls': [],
            'stats': {
                'total_downloaded': 0,
                'last_successful_date': None,
                'article_ids_by_page': {},
                'last_successful_ids': {}
            }
        }

        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    return json.load(f)
            return default_log
        except Exception as e:
            st.error(f"Error loading log file: {e}")
            return default_log

    def load_metadata(self):
        """Load or create the metadata file"""
        try:
            if os.path.exists(self.metadata_file):
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            st.error(f"Error loading metadata file: {e}")
            return {}

    def save_log(self):
        """Save the log file"""
        try:
            self.successful_urls['stats']['last_successful_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.log_file, 'w') as f:
                json.dump(self.successful_urls, f, indent=4)
        except Exception as e:
            st.error(f"Error saving log file: {e}")

    def save_metadata(self):
        """Save the metadata file"""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, indent=4, ensure_ascii=False)
        except Exception as e:
            st.error(f"Error saving metadata file: {e}")

    def get_article_metadata(self, soup, url, article_id):
        """Extract metadata from article page"""
        metadata = {
            'url': url,
            'article_id': article_id,
            'title': '',
            'date_scraped': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

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

    def download_image(self, url, folder_path, page, article_id):
        """Download image from article page"""
        try:
            if url in self.successful_urls['successful_urls']:
                return False, "Already downloaded"

            response = requests.get(url, headers=self.headers, timeout=10)

            if response.status_code != 200:
                self.consecutive_failures += 1
                return False, f"HTTP {response.status_code}"

            soup = BeautifulSoup(response.text, 'html.parser')
            img_tag = soup.find('img', id='current_artical')

            if not img_tag or 'src' not in img_tag.attrs:
                return False, "No image found"

            img_url = img_tag['src']
            os.makedirs(folder_path, exist_ok=True)

            img_response = requests.get(img_url, headers=self.headers, timeout=10)
            if img_response.status_code == 200:
                ext = os.path.splitext(urlparse(img_url).path)[1]
                if not ext:
                    ext = '.jpeg'

                filename = f'page{page}_article_{article_id}{ext}'
                filepath = os.path.join(folder_path, filename)

                with open(filepath, 'wb') as f:
                    f.write(img_response.content)

                metadata = self.get_article_metadata(soup, url, article_id)
                self.metadata[str(article_id)] = metadata
                self.save_metadata()

                self.consecutive_failures = 0
                self.successful_urls['successful_urls'].append(url)

                if str(page) not in self.successful_urls['stats']['article_ids_by_page']:
                    self.successful_urls['stats']['article_ids_by_page'][str(page)] = []

                if article_id not in self.successful_urls['stats']['article_ids_by_page'][str(page)]:
                    self.successful_urls['stats']['article_ids_by_page'][str(page)].append(article_id)

                self.successful_urls['stats']['last_successful_ids'][str(page)] = article_id
                self.successful_urls['stats']['total_downloaded'] += 1

                self.save_log()
                return True, filepath

            return False, "Failed to download image"

        except Exception as e:
            self.consecutive_failures += 1
            return False, str(e)

    def search_around_id(self, page, start_id, search_range=50):
        """
        Search for articles around the given ID.
        When a successful article is found, extend search by 10 IDs in both directions.
        """
        folder_path = os.path.join(self.base_folder, self.date_str)
        successful_downloads = []
        found_ids = set()  # Keep track of found article IDs
        ids_to_search = set(range(start_id - search_range, start_id + search_range + 1))

        progress_bar = st.progress(0)
        status_text = st.empty()
        search_stats = st.empty()

        while ids_to_search and self.consecutive_failures < self.max_consecutive_failures:
            current_id = min(ids_to_search)  # Start from lowest ID
            ids_to_search.remove(current_id)

            if current_id in found_ids:
                continue

            url = f'https://epaper.gujaratsamachar.com/view_article/ahmedabad/{self.date_str}/{page}/{current_id}'
            status_text.text(f"Trying URL: {url}")

            success, result = self.download_image(url, folder_path, page, current_id)

            if success:
                successful_downloads.append({
                    'article_id': current_id,
                    'url': url,
                    'filepath': result
                })
                found_ids.add(current_id)

                # Add 10 more IDs to search in both directions
                new_ids_lower = set(range(current_id - 10, current_id))
                new_ids_upper = set(range(current_id + 1, current_id + 11))
                new_ids = new_ids_lower.union(new_ids_upper)

                # Add new IDs to search set if they haven't been found yet
                ids_to_search.update(id for id in new_ids if id not in found_ids)

                # Reset consecutive failures counter
                self.consecutive_failures = 0

                # Update search statistics
                search_stats.text(f"""
                Found articles: {len(successful_downloads)}
                Remaining IDs to search: {len(ids_to_search)}
                Last successful ID: {current_id}
                """)

            # Update progress based on total searched vs total to search
            total_searched = len(found_ids) + len(ids_to_search)
            progress = len(found_ids) / total_searched if total_searched > 0 else 0
            progress_bar.progress(progress)

            time.sleep(0.5)  # Prevent too rapid requests

        if self.consecutive_failures >= self.max_consecutive_failures:
            status_text.text(f"Stopping search after {self.max_consecutive_failures} consecutive failures")
        else:
            status_text.text("Completed search for this page")

        # Sort downloads by article ID for better organization
        successful_downloads.sort(key=lambda x: x['article_id'])

        # Display final statistics for this page
        if found_ids:
            st.write(f"""
            ### Page {page} Summary
            - Total articles found: {len(successful_downloads)}
            - ID range: {min(found_ids)} to {max(found_ids)}
            - Search expanded {len(ids_to_search) - (2 * search_range)} additional IDs
            """)
        else:
            st.write(f"""
            ### Page {page} Summary
            - No articles found
            - Search range: {start_id - search_range} to {start_id + search_range}
            """)

        return successful_downloads

    def create_zip_file(self):
        """Create a zip file of all downloaded content"""
        zip_path = os.path.join(self.temp_dir, f'gujarat_samachar_{self.date_str}.zip')

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add images
                for root, dirs, files in os.walk(self.base_folder):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, self.temp_dir)
                        zipf.write(file_path, arcname)

                # Add metadata and log files
                if os.path.exists(self.metadata_file):
                    zipf.write(self.metadata_file, os.path.basename(self.metadata_file))
                if os.path.exists(self.log_file):
                    zipf.write(self.log_file, os.path.basename(self.log_file))

            return zip_path
        except Exception as e:
            st.error(f"Error creating zip file: {e}")
            return None

def extract_article_id(url):
    """Extract article ID from the URL"""
    match = re.search(r'/(\d+)$', url)
    if match:
        return int(match.group(1))
    return None

def create_download_link(zip_path):
    """Create a download link for the zip file"""
    try:
        with open(zip_path, 'rb') as f:
            bytes = f.read()
            b64 = base64.b64encode(bytes).decode()
            filename = os.path.basename(zip_path)
            href = f'<a href="data:application/zip;base64,{b64}" download="{filename}">Download ZIP File</a>'
            return href
    except Exception as e:
        st.error(f"Error creating download link: {e}")
        return None

def main():
    st.set_page_config(page_title="Gujarat Samachar Scraper", layout="wide")

    st.title("Gujarat Samachar E-Paper Scraper")

    # Create a temporary directory for this session
    with tempfile.TemporaryDirectory() as temp_dir:
        with st.sidebar:
            st.header("Settings")
            date_str = st.date_input(
                "Select Date",
                datetime.now()
            ).strftime('%d-%m-%Y')

            num_pages = st.number_input("Number of Pages to Scrape", min_value=1, max_value=20, value=4)
            search_range = st.number_input("Search Range Around Each ID", min_value=10, max_value=100, value=50)

        # Main content area
        st.header("Page URLs")

        # Create a form for URL inputs
        with st.form("url_inputs"):
            page_links = {}
            cols = st.columns(2)

            for page in range(1, num_pages + 1):
                with cols[page % 2]:
                    page_links[page] = st.text_input(
                        f"Starting URL for Page {page}",
                        help="Paste the full URL of any article on this page"
                    )

            submit_button = st.form_submit_button("Start Scraping")

        if submit_button:
            scraper = NewspaperScraper(date_str, temp_dir)

            # Create tabs for different views
            tab1, tab2, tab3 = st.tabs(["Progress", "Results", "Download"])

            with tab1:
                progress_container = st.container()

            with tab2:
                results_container = st.container()

            with tab3:
                download_container = st.container()

            all_downloads = []

            with progress_container:
                st.write("### Scraping Progress")

                overall_progress = st.progress(0)
                overall_status = st.empty()
                total_downloads = 0
                total_articles_found = 0

                for page_idx, page in enumerate(range(1, num_pages + 1)):
                    st.write(f"#### Processing Page {page}")

                    if page_links[page]:
                        start_id = extract_article_id(page_links[page])
                        if start_id:
                            overall_status.text(f"Processing page {page} of {num_pages}")
                            downloads = scraper.search_around_id(page, start_id, search_range)
                            all_downloads.extend(downloads)

                            total_articles_found += len(downloads)

                            st.write(f"""
                            Page {page} Complete:
                            - Articles found: {len(downloads)}
                            - Success rate: {(len(downloads)/search_range*100):.1f}%
                            """)
                        else:
                            st.error(f"Invalid URL format for page {page}")
                    else:
                        st.warning(f"No URL provided for page {page}")

                    overall_progress.progress((page_idx + 1) / num_pages)

                    # Update overall statistics
                    st.sidebar.metric("Total Articles Found", total_articles_found)
                    st.sidebar.metric("Pages Completed", page_idx + 1)

                overall_status.text("Scraping completed!")

            with results_container:
                st.write("### Scraping Results")

                # Display statistics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Downloads", len(all_downloads))
                with col2:
                    st.metric("Pages Processed", num_pages)
                with col3:
                    st.metric("Success Rate", f"{(len(all_downloads)/(num_pages*search_range*2))*100:.1f}%")

                # Display metadata
                if scraper.metadata:
                    st.write("#### Article Metadata")
                    metadata_df = pd.DataFrame(scraper.metadata).T
                    st.dataframe(metadata_df)

            with download_container:
                st.write("### Download Files")

                if all_downloads:
                    # Create zip file
                    zip_path = scraper.create_zip_file()
                    if zip_path:
                        # Create download link
                        href = create_download_link(zip_path)
                        if href:
                            st.markdown(href, unsafe_allow_html=True)

                            st.write("""
                            The ZIP file contains:
                            - All downloaded images
                            - Metadata file (article_metadata.json)
                            - Scraping log (scraping_log.json)
                            """)
                else:
                    st.warning("No files to download. Please run the scraper first.")

if __name__ == "__main__":
    main()
