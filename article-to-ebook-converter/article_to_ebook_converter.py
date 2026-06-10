#!/usr/bin/env python3
"""
Article to Ebook Converter
=====================
Converts URLs from a CSV file to individual EPUB files with images.

Features:
- Auto-detects urls.csv in Downloads folder
- Extracts article content with Readability algorithm
- Downloads and embeds images
- Converts links to underlined text (non-clickable)
- Smart author detection from website domain
- Saves EPUBs to Downloads/EPUBS folder
- Auto-cleanup of temporary files and CSV file

Creating standalone executable:
-------------------------------
pyinstaller --onefile --console --icon=icon.png --name "Article to Ebook Converter" csv_to_epub.py

Requirements:
------------
pip install readability-lxml ebooklib beautifulsoup4 requests
"""

import os
import re
import sys
import time
import hashlib
import uuid
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from ebooklib import epub

try:
    from readability import Document
except ImportError:
    print("\n" + "="*60)
    print("ERROR: Required packages not installed")
    print("="*60)
    print("\nPlease install required packages:")
    print("pip install readability-lxml ebooklib beautifulsoup4 requests")
    print("\n" + "="*60)
    input("\nPress Enter to exit...")
    sys.exit(1)

# Only import tkinter when needed (for file picker)
try:
    import tkinter as tk
    from tkinter import filedialog
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False
    print("Warning: tkinter not available. File picker will not work.")


def get_downloads_folder():
    """
    Get the Downloads folder path for Windows, Mac, and Linux.
    
    Returns:
        Path: Path object pointing to the Downloads folder
    """
    if sys.platform == "win32":
        # Windows: Read from registry
        try:
            import winreg
            sub_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
                downloads_path = winreg.QueryValueEx(key, '{374DE290-123F-4565-9164-39C4925E467B}')[0]
                return Path(downloads_path)
        except Exception:
            # Fallback to standard location
            return Path.home() / "Downloads"
    elif sys.platform == "darwin":
        # macOS
        return Path.home() / "Downloads"
    else:
        # Linux and others
        # Check for XDG user directories
        try:
            xdg_config = Path.home() / ".config" / "user-dirs.dirs"
            if xdg_config.exists():
                with open(xdg_config, 'r') as f:
                    for line in f:
                        if 'XDG_DOWNLOAD_DIR' in line:
                            path = line.split('=')[1].strip().strip('"')
                            path = path.replace('$HOME', str(Path.home()))
                            return Path(path)
        except Exception:
            pass
        # Fallback
        return Path.home() / "Downloads"


def find_csv_in_downloads():
    """
    Check Downloads folder for urls.csv or other CSV files.
    
    Returns:
        str or None: Path to CSV file if found, None otherwise
    """
    downloads = get_downloads_folder()
    
    # First, check specifically for urls.csv
    urls_csv = downloads / "urls.csv"
    if urls_csv.exists():
        print(f"✅ Found 'urls.csv' in Downloads folder")
        print(f"   Location: {urls_csv}")
        return str(urls_csv)
    
    # If urls.csv not found, look for other CSV files
    csv_files = list(downloads.glob("*.csv"))
    
    if len(csv_files) == 0:
        print(f"⚠️  No CSV files found in Downloads folder")
        print(f"   Location checked: {downloads}")
        return None
    elif len(csv_files) == 1:
        print(f"✅ Found one CSV file in Downloads: {csv_files[0].name}")
        return str(csv_files[0])
    else:
        print(f"⚠️  Found {len(csv_files)} CSV files in Downloads folder:")
        for i, csv_file in enumerate(csv_files, 1):
            print(f"   {i}. {csv_file.name}")
        print(f"\n   Please rename the correct file to 'urls.csv' and run again.")
        return None


def _select_csv_file_macos():
    """
    Open a native macOS file picker via AppleScript (osascript).

    Used as a fallback when tkinter is unavailable, and as the primary
    picker on macOS because it reliably appears in the foreground.

    Returns:
        str or None: POSIX path to selected file, None if cancelled
    """
    import subprocess

    downloads = str(get_downloads_folder())
    # AppleScript: choose a .csv file, default to the Downloads folder.
    script = f'''
        set defaultFolder to POSIX file "{downloads}"
        set chosenFile to choose file with prompt "Select CSV file with URLs" ¬
            of type {{"csv", "public.comma-separated-values-text", "public.text"}} ¬
            default location defaultFolder
        POSIX path of chosenFile
    '''
    try:
        print("\n📂 Opening file picker...")
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True
        )
        # User cancelled -> osascript exits non-zero with "User canceled."
        if result.returncode != 0:
            print("❌ No file selected")
            return None

        file_path = result.stdout.strip()
        if not file_path:
            print("❌ No file selected")
            return None

        print(f"✅ Selected file: {Path(file_path).name}\n")
        return file_path
    except Exception as e:
        print(f"❌ Error opening file picker: {e}")
        return None


def _select_csv_file_tkinter():
    """
    Open a tkinter file picker, forced to the foreground on macOS.

    Returns:
        str or None: Path to selected file, None if cancelled
    """
    try:
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        # Force the dialog to the front (otherwise it hides behind the
        # terminal on macOS and looks like nothing happened).
        root.attributes('-topmost', True)
        root.update()

        print("\n📂 Opening file picker...")
        file_path = filedialog.askopenfilename(
            parent=root,
            title="Select CSV file with URLs",
            filetypes=[
                ("CSV files", "*.csv"),
                ("All files", "*.*")
            ],
            initialdir=get_downloads_folder()
        )
        root.destroy()

        if not file_path:
            print("❌ No file selected")
            return None

        print(f"✅ Selected file: {Path(file_path).name}\n")
        return file_path
    except Exception as e:
        print(f"❌ Error opening file picker: {e}")
        return None


def select_csv_file():
    """
    Open a file picker dialog to select a CSV file.

    On macOS, prefer the native AppleScript picker (reliable foreground
    behavior). Elsewhere, use tkinter. Falls back to tkinter on macOS if
    the native picker fails.

    Returns:
        str or None: Path to selected file, None if cancelled
    """
    if sys.platform == "darwin":
        file_path = _select_csv_file_macos()
        if file_path is not None:
            return file_path
        # If the native picker hard-failed (not a user cancel), try tkinter.
        if TKINTER_AVAILABLE:
            return _select_csv_file_tkinter()
        return None

    if not TKINTER_AVAILABLE:
        print("❌ File picker not available (tkinter not installed)")
        return None

    return _select_csv_file_tkinter()


def open_folder_in_explorer(folder_path):
    """
    Open folder in system file explorer (Windows/Mac/Linux).
    
    Args:
        folder_path (str): Path to folder to open
    """
    try:
        if sys.platform == "win32":
            os.startfile(folder_path)
        elif sys.platform == "darwin":
            os.system(f'open "{folder_path}"')
        else:
            os.system(f'xdg-open "{folder_path}"')
        print(f"📂 Opened folder in file explorer")
    except Exception as e:
        print(f"⚠️  Could not open folder: {e}")


class CSVToEPUBConverter:
    """
    Main converter class that handles the entire CSV to EPUB conversion process.
    """
    
    def __init__(self, csv_file=None, output_dir=None):
        """
        Initialize the converter.
        
        Args:
            csv_file (str, optional): Path to CSV file
            output_dir (str, optional): Directory for output EPUB files
        """
        self.csv_file = Path(csv_file) if csv_file else Path('urls.csv')
        self.output_dir = Path(output_dir) if output_dir else get_downloads_folder() / "EPUBS"
        self.images_dir = self.output_dir / 'temp_images'
        self.created_epubs = []
        
        # Create directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup session for web requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        # Supported image formats
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp'}

    def extract_website_name(self, url):
        """
        Extract a clean, readable website name from URL to use as author.
        
        Args:
            url (str): The URL to extract website name from
            
        Returns:
            str: Formatted website name
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            
            # Mapping of common domains to their readable names
            domain_mappings = {
                'wikipedia.org': 'Wikipedia',
                'reddit.com': 'Reddit',
                'medium.com': 'Medium',
                'substack.com': 'Substack',
                'wordpress.com': 'WordPress',
                'blogspot.com': 'Blogger',
                'nytimes.com': 'The New York Times',
                'washingtonpost.com': 'The Washington Post',
                'wsj.com': 'The Wall Street Journal',
                'cnn.com': 'CNN',
                'bbc.com': 'BBC',
                'bbc.co.uk': 'BBC',
                'theguardian.com': 'The Guardian',
                'reuters.com': 'Reuters',
                'apnews.com': 'Associated Press',
                'forbes.com': 'Forbes',
                'bloomberg.com': 'Bloomberg',
                'techcrunch.com': 'TechCrunch',
                'wired.com': 'Wired',
                'arstechnica.com': 'Ars Technica',
                'theregister.com': 'The Register',
                'zdnet.com': 'ZDNet',
                'engadget.com': 'Engadget',
                'theverge.com': 'The Verge',
                '404media.co': '404 Media',
                'github.com': 'GitHub',
                'stackoverflow.com': 'Stack Overflow',
                'hackernews.ycombinator.com': 'Hacker News',
                'news.ycombinator.com': 'Hacker News',
            }
            
            # Check for exact matches
            if domain in domain_mappings:
                return domain_mappings[domain]
            
            # Check for subdomain matches
            for mapped_domain, mapped_name in domain_mappings.items():
                if domain.endswith('.' + mapped_domain):
                    return mapped_name
            
            # For unknown domains, create a readable name
            domain_parts = domain.split('.')
            if len(domain_parts) >= 2:
                main_part = domain_parts[0]
                
                # Skip common prefixes
                if main_part in ['en', 'www', 'blog', 'news', 'www2', 'de', 'fr', 'es']:
                    main_part = domain_parts[1] if len(domain_parts) >= 3 else domain_parts[0]
                
                # Convert to readable format (handle camelCase and kebab-case)
                readable_name = re.sub(r'([a-z])([A-Z])', r'\1 \2', main_part)
                readable_name = readable_name.replace('-', ' ').replace('_', ' ')
                readable_name = ' '.join(word.capitalize() for word in readable_name.split())
                
                return readable_name
            
            # Fallback: capitalize the domain
            return domain.replace('.', ' ').title()
            
        except Exception as e:
            print(f"⚠️  Error extracting article name from {url}: {e}")
            return "Unknown Source"

    def read_urls_from_csv(self):
        """
        Read URLs from CSV file, handling various formats.
        Supports:
        - Single URL per line
        - Comma-separated URLs on one line
        - With or without header row
        
        Returns:
            list: List of valid URLs
        """
        urls = []
        try:
            with open(self.csv_file, 'r', encoding='utf-8') as file:
                # Read first line to check for header
                first_line = file.readline().strip()
                file.seek(0)
                
                # Skip header if it doesn't look like a URL
                if first_line and not first_line.startswith('http'):
                    next(file)
                
                # Read all remaining content
                content = file.read()
                
                # Process line by line, then split by commas
                lines = content.strip().split('\n')
                for line in lines:
                    if line.strip():
                        # Split by comma and clean each URL
                        line_urls = [url.strip().rstrip(',') for url in line.split(',')]
                        for url in line_urls:
                            if url and self._is_valid_url(url):
                                urls.append(url)
                                
        except Exception as e:
            print(f"❌ Error reading CSV file: {e}")
            return []
            
        return urls

    def _is_valid_url(self, url):
        """
        Validate if a string is a proper URL.
        
        Args:
            url (str): URL string to validate
            
        Returns:
            bool: True if valid URL, False otherwise
        """
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False

    def download_image(self, img_url, base_url):
        """
        Download an image from URL and save locally.
        
        Args:
            img_url (str): Image URL (can be relative)
            base_url (str): Base URL for resolving relative paths
            
        Returns:
            str or None: Local filename if successful, None otherwise
        """
        try:
            # Resolve relative URLs
            if img_url.startswith('//'):
                img_url = 'https:' + img_url
            elif img_url.startswith('/'):
                img_url = urljoin(base_url, img_url)
            elif not img_url.startswith('http'):
                img_url = urljoin(base_url, img_url)
            
            # Check if URL has image extension
            parsed = urlparse(img_url)
            path_lower = parsed.path.lower()
            
            if not any(path_lower.endswith(ext) for ext in self.image_extensions):
                return None
            
            # Create safe filename using hash
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:10]
            
            # Determine file extension
            ext = next((e for e in self.image_extensions if path_lower.endswith(e)), '.jpg')
            filename = f"img_{url_hash}{ext}"
            filepath = self.images_dir / filename
            
            # Download if not already cached
            if not filepath.exists():
                response = self.session.get(img_url, timeout=10, stream=True)
                response.raise_for_status()
                
                # Verify content type
                content_type = response.headers.get('content-type', '').lower()
                if not content_type.startswith('image/'):
                    return None
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                print(f"   📥 Downloaded image: {filename}")
            
            return filename
            
        except Exception as e:
            print(f"   ⚠️  Failed to download image: {e}")
            return None

    def convert_links_to_underlined_text(self, soup):
        """
        Convert all <a> tags to non-clickable underlined text.
        
        Args:
            soup (BeautifulSoup): Parsed HTML content
            
        Returns:
            BeautifulSoup: Modified soup with links converted
        """
        for link in soup.find_all('a'):
            link_text = link.get_text().strip()
            link_url = link.get('href', '')
            
            # Create span with underline styling
            new_span = soup.new_tag('span', style='text-decoration: underline;')
            
            # Use link text if available, otherwise use URL
            if link_text:
                new_span.string = link_text
            elif link_url:
                new_span.string = link_url
            else:
                new_span.string = '[link]'
            
            link.replace_with(new_span)
        
        return soup

    def extract_article_with_images(self, url):
        """
        Extract article content from URL with images.
        
        Args:
            url (str): Article URL
            
        Returns:
            dict or None: Article data including title, content, images
        """
        try:
            print(f"   📄 Fetching content...")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            if response.encoding is None:
                response.encoding = 'utf-8'
            
            # Use Readability for content extraction
            doc = Document(response.text)
            title = doc.title()
            content = doc.summary()
            
            # Fallback if Readability returns minimal content
            if not content or len(content.strip()) < 100:
                print("   ℹ️  Using fallback extraction method...")
                soup = BeautifulSoup(response.text, 'html.parser')
                content = self._fallback_extraction(soup)
                title = title or self._extract_title(soup)
            
            # Parse content with BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Remove unwanted elements
            for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']):
                tag.decompose()
            
            # Convert links to underlined text
            soup = self.convert_links_to_underlined_text(soup)
            
            # Download and embed images
            downloaded_images = {}
            for img in soup.find_all('img'):
                img_src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if img_src:
                    local_filename = self.download_image(img_src, url)
                    if local_filename:
                        downloaded_images[local_filename] = img_src
                        img['src'] = local_filename
                        # Clean up extra attributes
                        for attr in ['data-src', 'data-lazy-src', 'srcset', 'data-srcset']:
                            if img.has_attr(attr):
                                del img[attr]
                    else:
                        # Remove image if download failed
                        img.decompose()
            
            # Remove empty paragraphs
            for p in soup.find_all('p'):
                if not p.get_text().strip() and not p.find('img'):
                    p.decompose()
            
            return {
                'title': title or "Extracted Article",
                'content': str(soup),
                'url': url,
                'images': downloaded_images
            }
            
        except requests.exceptions.Timeout:
            print(f"   ❌ Timeout: Server took too long to respond")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"   ❌ HTTP Error: {e}")
            return None
        except Exception as e:
            print(f"   ❌ Error extracting article: {e}")
            return None

    def _extract_title(self, soup):
        """Extract title from HTML using common selectors."""
        title_selectors = [
            'h1',
            'title',
            '[property="og:title"]',
            '[name="twitter:title"]',
            '.entry-title',
            '.post-title',
            '.article-title'
        ]
        
        for selector in title_selectors:
            element = soup.select_one(selector)
            if element:
                title = element.get_text().strip()
                if title:
                    return title
        
        return "Extracted Article"

    def _fallback_extraction(self, soup):
        """Fallback content extraction when Readability fails."""
        # Remove unwanted elements
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']):
            tag.decompose()
        
        # Try common content selectors
        content_selectors = [
            'article',
            '.entry-content',
            '.post-content',
            '.article-content',
            '.content',
            'main',
            '[role="main"]'
        ]
        
        for selector in content_selectors:
            content_element = soup.select_one(selector)
            if content_element:
                return str(content_element)
        
        # Last resort: find element with most text
        text_elements = soup.find_all(['div', 'section', 'article'], string=False)
        if text_elements:
            best_element = max(text_elements, key=lambda x: len(x.get_text()) if x.get_text() else 0)
            if len(best_element.get_text()) > 200:
                return str(best_element)
        
        return "<p>Could not extract article content</p>"

    def create_epub(self, article_data):
        """
        Create EPUB file from article data.
        
        Args:
            article_data (dict): Article content and metadata
            
        Returns:
            Path or None: Path to created EPUB file, None if failed
        """
        try:
            title = article_data['title']
            content = article_data['content']
            url = article_data['url']
            images = article_data['images']
            
            # Extract website name for author
            website_author = self.extract_website_name(url)
            
            # Create EPUB book
            book = epub.EpubBook()
            book.set_identifier(str(uuid.uuid4()))
            book.set_title(title)
            book.set_language('en')
            book.add_author(website_author)
            
            # Add images to EPUB
            image_items = {}
            for local_filename, original_url in images.items():
                image_path = self.images_dir / local_filename
                if image_path.exists():
                    with open(image_path, 'rb') as img_file:
                        img_content = img_file.read()
                    
                    # Determine media type
                    ext = Path(local_filename).suffix.lower()
                    media_type_map = {
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.png': 'image/png',
                        '.gif': 'image/gif',
                        '.webp': 'image/webp',
                        '.svg': 'image/svg+xml',
                        '.bmp': 'image/bmp'
                    }
                    media_type = media_type_map.get(ext, 'image/jpeg')
                    
                    # Create EPUB image item
                    img_item = epub.EpubImage(
                        uid=f"img_{local_filename}",
                        file_name=f"images/{local_filename}",
                        media_type=media_type,
                        content=img_content
                    )
                    
                    book.add_item(img_item)
                    image_items[local_filename] = f"images/{local_filename}"
            
            # Update image paths in content
            soup = BeautifulSoup(content, 'html.parser')
            for img in soup.find_all('img'):
                src = img.get('src')
                if src in image_items:
                    img['src'] = image_items[src]
            
            content = str(soup)
            
            # Create chapter with styling
            chapter_content = f"""
            <html>
            <head>
                <title>{title}</title>
                <style>
                    body {{
                        font-family: Georgia, serif;
                        line-height: 1.6;
                        padding: 1em;
                    }}
                    h1 {{
                        font-size: 1.8em;
                        margin-bottom: 0.5em;
                    }}
                    img {{
                        max-width: 100%;
                        height: auto;
                        margin: 1em 0;
                    }}
                    span[style*="text-decoration: underline"] {{
                        text-decoration: underline;
                        color: #0066cc;
                    }}
                </style>
            </head>
            <body>
                <h1>{title}</h1>
                <p><em>Source: <span style="text-decoration: underline;">{url}</span></em></p>
                <hr/>
                {content}
            </body>
            </html>
            """
            
            chapter = epub.EpubHtml(
                title=title,
                file_name='chapter.xhtml',
                lang='en'
            )
            chapter.content = chapter_content
            
            book.add_item(chapter)
            
            # Create table of contents
            book.toc = (epub.Link("chapter.xhtml", title, "chapter"),)
            
            # Add navigation
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            
            # Define spine
            book.spine = ['nav', chapter]
            
            # Create safe filename
            safe_title = re.sub(r'[^\w\s-]', '', title)
            safe_title = re.sub(r'[-\s]+', '-', safe_title).strip('-')[:100]
            if not safe_title:
                safe_title = "article"
            
            # Handle duplicate filenames
            epub_file = self.output_dir / f"{safe_title}.epub"
            counter = 1
            while epub_file.exists():
                epub_file = self.output_dir / f"{safe_title}_{counter}.epub"
                counter += 1
            
            # Write EPUB file
            epub.write_epub(str(epub_file), book, {})
            
            self.created_epubs.append(epub_file)
            
            print(f"   ✅ Created: {epub_file.name}")
            print(f"   📝 Author: {website_author}")
            return epub_file
            
        except Exception as e:
            print(f"   ❌ Error creating EPUB: {e}")
            return None

    def cleanup_temp_images(self):
        """Clean up temporary image files and directory."""
        try:
            if self.images_dir.exists():
                # Delete all image files
                image_files = list(self.images_dir.glob('*'))
                for img_file in image_files:
                    try:
                        img_file.unlink()
                    except Exception as e:
                        print(f"   ⚠️  Could not delete {img_file.name}: {e}")
                
                # Remove directory if empty
                try:
                    if not any(self.images_dir.iterdir()):
                        self.images_dir.rmdir()
                        print("   🧹 Cleaned up temporary files")
                except Exception:
                    pass
        except Exception as e:
            print(f"   ⚠️  Error during cleanup: {e}")

    def convert_csv_to_epubs(self, delay_between_requests=2.0):
        """
        Main conversion method - processes all URLs from CSV.
        
        Args:
            delay_between_requests (float): Seconds to wait between requests
            
        Returns:
            bool: True if at least one conversion succeeded
        """
        print("\n" + "="*60)
        print("🚀 Starting Article to Ebook Conversion")
        print("="*60 + "\n")
        
        # Verify CSV file exists
        if not self.csv_file.exists():
            print(f"❌ CSV file not found: {self.csv_file}")
            return False
        
        # Read URLs from CSV
        urls = self.read_urls_from_csv()
        if not urls:
            print("❌ No valid URLs found in CSV file")
            return False
        
        print(f"📋 Found {len(urls)} URL(s) to process\n")
        
        # Process each URL
        success_count = 0
        failed_urls = []
        
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] Processing: {url}")
            
            try:
                # Extract and convert
                article_data = self.extract_article_with_images(url)
                if article_data:
                    epub_file = self.create_epub(article_data)
                    if epub_file:
                        success_count += 1
                    else:
                        failed_urls.append(url)
                else:
                    failed_urls.append(url)
                
                # Delay between requests (except for last URL)
                if i < len(urls):
                    time.sleep(delay_between_requests)
                    
            except Exception as e:
                print(f"   ❌ Unexpected error: {e}")
                failed_urls.append(url)
            
            print()  # Blank line between URLs
        
        # Cleanup
        self.cleanup_temp_images()
        
        # Print summary
        print("="*60)
        print("📊 Conversion Summary")
        print("="*60)
        print(f"✅ Successful: {success_count}/{len(urls)}")
        print(f"❌ Failed: {len(failed_urls)}/{len(urls)}")
        
        if failed_urls:
            print(f"\nFailed URLs:")
            for url in failed_urls:
                print(f"  • {url}")
        
        print(f"\n📁 Output location: {self.output_dir}")
        print("="*60 + "\n")
        
        return success_count > 0


def main():
    """Main application entry point."""
    try:
        # Print header
        print("\n" + "="*60)
        print("📚 Article to Ebook Converter")
        print("="*60)
        print("\nThis program will:")
        print("  1. Look for 'urls.csv' in your Downloads folder")
        print("  2. Extract article content from each URL")
        print("  3. Download images from articles")
        print("  4. Convert links to non-clickable underlined text")
        print("  5. Create EPUB files with clean formatting")
        print("  6. Save EPUBs to Downloads/EPUBS folder")
        print("  7. Set website name as author (e.g., Wikipedia)")
        print("  8. Auto-delete the CSV file when done")
        print("="*60 + "\n")
        
        # Step 1: Find CSV file
        print("🔍 Step 1: Looking for CSV file...")
        csv_file = find_csv_in_downloads()
        
        # Step 2: If not found, ask user to locate it
        if csv_file is None:
            print("\n⚠️  Could not auto-locate CSV file")
            csv_file = select_csv_file()
            if not csv_file:
                print("\n❌ No file selected. Exiting.\n")
                input("Press Enter to exit...")
                return
        
        # Step 3: Setup output directory
        downloads = get_downloads_folder()
        output_folder = downloads / "EPUBS"
        print(f"\n📁 Output folder: {output_folder}\n")
        
        # Step 4: Create converter and process
        converter = CSVToEPUBConverter(
            csv_file=csv_file,
            output_dir=output_folder
        )
        
        success = converter.convert_csv_to_epubs(delay_between_requests=2.0)
        
        # Step 5: Handle completion
        if success:
            print("✅ Conversion completed successfully!\n")
            
            # Delete the CSV file
            try:
                csv_path = Path(csv_file)
                if csv_path.exists():
                    csv_path.unlink()
                    print(f"🗑️  Deleted CSV file: {csv_path.name}")
            except Exception as e:
                print(f"⚠️  Could not delete CSV file: {e}")
            
            # Open output folder
            print("\n📂 Opening output folder...")
            open_folder_in_explorer(str(output_folder))
            
            print("\n" + "="*60)
            print("✨ All done! Your EPUB files are ready.")
            print("="*60)
            input("\nPress Enter to exit...")
        else:
            print("❌ Conversion completed with errors")
            print("   Check the messages above for details.\n")
            input("Press Enter to exit...")
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Process interrupted by user")
        input("\nPress Enter to exit...")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()