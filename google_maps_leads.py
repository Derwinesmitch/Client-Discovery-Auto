
import time
import random
import csv
import logging
import os
import sys

# Try to import undetected_chromedriver
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError as e:
    print(f"Critical Error: Required libraries not found. Details: {e}")
    print("Please run: pip install undetected-chromedriver selenium")
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred during import: {e}")
    sys.exit(1)

# --- CONFIGURATION SECTION ---
# Update these selectors if Google Maps structure changes.
# Use 'Inspect Element' (F12) in your browser to verify these class names.

### CSS SELECTORS ###
# The container for the *list* of results in the sidebar. 
# Usually has role="feed" or similar. We often find the individual items inside.
# Google often uses these specific classes for result containers
RESULT_ITEM_SELECTOR = 'div[role="article"]' 

# The specific icon/text that indicates a website. 
# Look for the 'globe' icon or the text 'Website' in the details panel.
# E.g., a button with data-item-id="authority" or labeled "Website"
WEBSITE_BUTTON_SELECTOR = 'a[data-item-id="authority"]'

# Business Name in the details panel (side panel that opens after clicking)
BUSINESS_NAME_SELECTOR = 'h1.DUwDvf' 

# Phone number in the details panel. 
# Often has a specific aria-label or starts with 'tel:' in href, but visually it's a button.
# We will look for a button that contains the phone icon or starts with specific text.
# A generic approach is safe: buttons with data-item-id starting with "phone"
PHONE_BUTTON_SELECTOR = 'button[data-item-id^="phone"]'
#######################

MAX_LEADS_TO_CHECK = 50
CSV_FILENAME = 'leads.csv'

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class LeadFinder:
    def __init__(self):
        self.driver = None
        self.leads_found = 0
        self.checked_count = 0
        self.existing_leads = set()
        self.load_existing_leads()

    def load_existing_leads(self):
        """Load existing phone numbers/names from CSV to avoid duplicates."""
        if os.path.exists(CSV_FILENAME):
            with open(CSV_FILENAME, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None) # Skip header
                for row in reader:
                    if len(row) >= 2:
                        # Store phone number as unique identifier (or name if phone is N/A)
                        self.existing_leads.add(row[1] if row[1] != "N/A" else row[0])
        logger.info(f"Loaded {len(self.existing_leads)} existing leads from CSV.")

    def init_browser(self):
        """Initialize undetected-chromedriver."""
        logger.info("Initializing browser...")
        options = uc.ChromeOptions()
        # Randomize window size slightly to look more human
        options.add_argument(f"--window-size={random.randint(1000, 1400)},{random.randint(800, 1000)}")
        
        # NOTE: Headless mode often triggers Google's anti-bot easier. 
        # Keeping it visible (headless=False) is recommended for undetected-chromedriver.
        self.driver = uc.Chrome(options=options)
        logger.info("Browser initialized.")

    def human_sleep(self, min_seconds=2, max_seconds=5):
        """Random sleep to mimic human behavior."""
        sleep_time = random.uniform(min_seconds, max_seconds)
        time.sleep(sleep_time)

    def save_lead(self, name, phone, query):
        """Save a valid lead to CSV immediately."""
        
        # Deduplication check
        unique_id = phone if phone != "N/A" else name
        if unique_id in self.existing_leads:
            logger.info(f"Duplicate lead found (already in CSV): {name}. Skipping save.")
            return

        file_exists = os.path.isfile(CSV_FILENAME)
        with open(CSV_FILENAME, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Business Name', 'Phone', 'Search Query', 'Timestamp']) # Header
            writer.writerow([name, phone, query, time.strftime("%Y-%m-%d %H:%M:%S")])
            
        self.existing_leads.add(unique_id)
        logger.info(f"*** LEAD SAVED: {name} | {phone} ***")
        self.leads_found += 1

    def scroll_sidebar(self):
        """
        Scrolls the results list sidebar to load more items.
        Google Maps loads results dynamically. We need to find the scrollable container.
        """
        try:
            # We look for the feed container. This is a common aria-label for the list.
            # If this fails, we might need to fallback to 'body' or different div logic
            scrollable_div = self.driver.find_element(By.CSS_SELECTOR, 'div[role="feed"]')
            
            # Scroll down using JS
            self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollable_div)
            logger.info("Scrolled sidebar...")
            self.human_sleep(2, 4) # Wait for load
            
            # Check if we reached the end warning (optional enhancement)
            # msg_elements = self.driver.find_elements(By.CssSelector, "span.HlvSq") 
        except Exception as e:
            logger.warning(f"Could not scroll sidebar (might be initial load or end of list): {e}")

    def check_external_website(self, name, query_location):
        """
        Opens a new tab to search Google for the business name.
        Returns True if a likely official website is found.
        """
        logger.info(f"Double-checking: Is there a website for '{name}' on Google Search?")
        original_window = self.driver.current_window_handle
        
        try:
            # Open new tab
            self.driver.execute_script("window.open('');")
            self.human_sleep(0.5, 1) # Wait for tab to open
            
            check_handles = self.driver.window_handles
            if len(check_handles) <= 1:
                logger.warning("Could not open new tab for check. Skipping verification to be safe.")
                return False

            self.driver.switch_to.window(check_handles[-1])
            
            # Additional safety: Ensure we are NOT on the main maps window
            if self.driver.current_window_handle == original_window:
                logger.warning("Switched to wrong window. Aborting check.")
                return False
            
            # Search Google
            # We add the location from the user's original query to narrow it down
            # e.g. "Clinica Zanon Asuncion"
            # We strip generic terms like "Dentists in" from the query if possible, but appending the whole query is usually fine.
            # Let's try to extract just the location from the query "Dentists in Asuncion" -> "Asuncion"
            # distinct_location = query_location.split(" in ")[-1] if " in " in query_location else query_location
            
            search_q = f"{name} {query_location}"
            self.driver.get(f"https://www.google.com/search?q={search_q}")
            
            self.human_sleep(2, 4)
            
            # logic: Look at first 3 results. 
            # If any of them are NOT common directories/social media, it's likely a website.
            
            ignored_domains = [
                "facebook.com", "instagram.com", "linkedin.com", 
                "yelp.com", "tripadvisor.com", "yellowpages.com", 
                "mapquest.com", "tiktok.com", "twitter.com", 
                "google.com", "waze.com", "foursquare.com"
            ]
            
            # Common selector for search results stats/links
            # This selector represents the main link in a search result
            links = self.driver.find_elements(By.CSS_SELECTOR, "div.g a")
            
            found_likely_website = False
            processed_count = 0
            
            for link in links:
                if processed_count >= 3: break # Only check top 3
                
                href = link.get_attribute("href")
                if not href: continue
                
                # Check if it's an ignored domain
                is_ignored = any(d in href for d in ignored_domains)
                
                if not is_ignored:
                    logger.info(f"Found likely website: {href}")
                    found_likely_website = True
                    break
                
                processed_count += 1
                
            return found_likely_website

        except Exception as e:
            logger.warning(f"Secondary check failed for {name}: {e}")
            return False # Assume no website if check fails, to be safe/greedy
        finally:
            # Always close tab and return to maps
            try:
                # Only close if we are currently on a different window than the original
                if len(self.driver.window_handles) > 1 and self.driver.current_window_handle != original_window:
                    self.driver.close()
                self.driver.switch_to.window(original_window)
            except Exception as e:
                logger.warning(f"Error switching back to main window: {e}")

    def extract_data(self, query):
        """Iterate through loaded results and check for website."""
        logger.info("Starting extraction loop...")

        # We need to re-find elements often because DOM updates detach them
        processed_indices = set()

        while self.checked_count < MAX_LEADS_TO_CHECK:
            # Find all current result items
            results = self.driver.find_elements(By.CSS_SELECTOR, RESULT_ITEM_SELECTOR)
            
            # Filter out processed ones by index to avoid re-clicking same ones in this session
            # Note: This is a simple logic. In a long scroll, checking by index is fragile if list updates at top.
            # Better might be checking visible text, but index is okay for simple runs.
            
            current_batch_count = len(results)
            logger.info(f"Found {current_batch_count} results loaded so far.")

            found_new_in_batch = False

            for i in range(current_batch_count):
                if self.checked_count >= MAX_LEADS_TO_CHECK:
                    break
                
                if i in processed_indices:
                    continue
                
                found_new_in_batch = True
                processed_indices.add(i)
                self.checked_count += 1

                # Re-fetch the list to avoid StaleElementReferenceException
                results = self.driver.find_elements(By.CSS_SELECTOR, RESULT_ITEM_SELECTOR)
                if i >= len(results):
                    break # List might have shifted?
                
                item = results[i]
                
                try:
                    # Scroll item into view before clicking
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
                    self.human_sleep(1, 2)
                    item.click()
                    
                    # Wait for details panel to load
                    self.human_sleep(2, 4)
                    
                    # Check for website button
                    has_website = False
                    try:
                        # Short timeout to check for website button
                        WebDriverWait(self.driver, 3).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, WEBSITE_BUTTON_SELECTOR))
                        )
                        has_website = True
                    except:
                        has_website = False

                    # Get Name
                    name = "Unknown"
                    try:
                        name_el = self.driver.find_element(By.CSS_SELECTOR, BUSINESS_NAME_SELECTOR)
                        name = name_el.text.strip()
                    except:
                        pass # Keep Unknown

                    if not has_website:
                        logger.info(f"Checking {name}: No Website on Maps...")
                        
                        # --- SECONDARY VERIFICATION ---
                        # Check normal Google Search to see if they actually DO have a website
                        # We use the 'query' variable which contains the location (e.g. "Dentists in Asuncion")
                        # to give context to the search check.
                        
                        has_hidden_website = self.check_external_website(name, query)
                        
                        if has_hidden_website:
                            logger.info(f"Skipping {name}: Found likely website on Google Search.")
                        else:
                            logger.info(f"{name} is a VALID LEAD (No site on Maps, No obvious site on Google).")
                            
                            # Get Phone
                            phone = "N/A"
                            try:
                                # Try to find the button containing the phone number
                                phone_btn = self.driver.find_element(By.CSS_SELECTOR, PHONE_BUTTON_SELECTOR)
                                # The phone number is usually in the aria-label or specific child div
                                # Validating via aria-label is often robust
                                phone = phone_btn.get_attribute("aria-label") or phone_btn.text
                                phone = phone.replace("Phone: ", "") # Clean up commonly found text
                            except:
                                pass # Phone not listed

                            self.save_lead(name, phone, query)
                    else:
                        logger.info(f"Checking {name}: Has website. Skipping.")

                except Exception as e:
                    logger.error(f"Error processing item index {i}: {e}")
                    continue
                
                # Small pause between items
                self.human_sleep(1, 3)

            # If we didn't find any new items in this pass, we need to scroll more
            if not found_new_in_batch or (len(processed_indices) >= current_batch_count):
                self.scroll_sidebar()
                # If scroll didn't add new items, we might be stuck or at end.
                new_results = self.driver.find_elements(By.CSS_SELECTOR, RESULT_ITEM_SELECTOR)
                if len(new_results) == current_batch_count:
                    logger.info("No new results after scrolling. Trying one more time...")
                    self.human_sleep(3, 5)
                    self.scroll_sidebar()
                    new_results_2 = self.driver.find_elements(By.CSS_SELECTOR, RESULT_ITEM_SELECTOR)
                    if len(new_results_2) == current_batch_count:
                        logger.info("Reached end of results or scroll stuck. Finishing.")
                        break

    def run(self):
        print("--- Google Maps Lead Finder ---")
        print("This tool can scan multiple locations for a specific niche.")
        
        niche = input("Enter Niche (e.g., 'Dentists', 'Restaurants'): ").strip()
        locations_input = input("Enter Locations (comma separated, e.g., 'Downtown, Uptown, Asuncion'): ").strip()
        
        if not niche or not locations_input:
            print("Inputs cannot be empty. Exiting.")
            return

        locations = [loc.strip() for loc in locations_input.split(',')]
        
        self.init_browser()
        
        total_locations = len(locations)
        
        try:
            for index, location in enumerate(locations):
                query = f"{niche} in {location}"
                logger.info(f"--- Starting Search {index + 1}/{total_locations}: {query} ---")
                
                # OPTIMIZATION: Navigate directly to the search URL. 
                # This is more robust than finding the search box and typing.
                search_url = f"https://www.google.com/maps/search/{query}"
                logger.info(f"Navigating directly to: {search_url}")
                self.driver.get(search_url)

                # Wait for results to appear
                logger.info("Waiting for results to load...")
                
                # Sometimes a cookie consent might block interaction or loading
                # We add a long wait and a manual sleep to be safe
                self.human_sleep(5, 7) 

                try:
                    wait = WebDriverWait(self.driver, 30)
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, RESULT_ITEM_SELECTOR)))
                    
                    self.extract_data(query)
                except Exception as e:
                    logger.warning(f"Could not load results for {location}: {e}")

                # Anti-Ban Pause between locations
                if index < total_locations - 1:
                    pause_time = random.randint(15, 25)
                    logger.info(f"Taking a safety break of {pause_time} seconds before next location...")
                    time.sleep(pause_time)
            
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
        finally:
            logger.info(f"Done. Checked {self.checked_count} businesses. Found {self.leads_found} leads.")
            if self.driver:
                self.driver.quit()

if __name__ == "__main__":
    finder = LeadFinder()
    finder.run()
