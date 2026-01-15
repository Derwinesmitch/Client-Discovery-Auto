
import time
import random
import csv
import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# Try to import undetected_chromedriver
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError as e:
    print(f"Critical Error: Required libraries not found. Details: {e}")
    sys.exit(1)

# --- PATCH FOR WINDOWS GHOST ERROR ---
def safe_destructor(self):
    try:
        self.quit()
    except OSError:
        pass
uc.Chrome.__del__ = safe_destructor
# -------------------------------------

# --- CONFIGURATION SECTION ---
RESULT_ITEM_SELECTOR = 'div[role="article"]' 
WEBSITE_BUTTON_SELECTOR = 'a[data-item-id="authority"]'
BUSINESS_NAME_SELECTOR = 'h1.DUwDvf' 
PHONE_BUTTON_SELECTOR = 'button[data-item-id^="phone"]'

MAX_LEADS_TO_CHECK = 50
CSV_FILENAME = 'leads.csv'

# Setup logging to be redirected to GUI later
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class TextHandler(logging.Handler):
    """This class allows getting log messages into the Tkinter Text widget."""
    def __init__(self, text_widget):
        logging.Handler.__init__(self)
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.yview(tk.END)
        # Verify if widget exists (app might be closed)
        try:
            self.text_widget.after(0, append)
        except:
            pass

class LeadFinder:
    def __init__(self, log_widget=None):
        self.driver = None
        self.leads_found = 0
        self.checked_count = 0
        self.existing_leads = set()
        self.load_existing_leads()
        self.stop_requested = False
        self.log_widget = log_widget

    def load_existing_leads(self):
        """Load existing phone numbers/names from CSV to avoid duplicates."""
        if os.path.exists(CSV_FILENAME):
            try:
                with open(CSV_FILENAME, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader, None) # Skip header
                    for row in reader:
                        if len(row) >= 2:
                            self.existing_leads.add(row[1] if row[1] != "N/A" else row[0])
            except Exception as e:
                logger.error(f"Error loading CSV: {e}")

    def init_browser(self):
        """Initialize undetected-chromedriver."""
        logger.info("Initializing browser...")
        options = uc.ChromeOptions()
        options.add_argument(f"--window-size={random.randint(1000, 1400)},{random.randint(800, 1000)}")
        self.driver = uc.Chrome(options=options)
        logger.info("Browser initialized.")

    def human_sleep(self, min_seconds=2, max_seconds=5):
        if self.stop_requested: return
        time.sleep(random.uniform(min_seconds, max_seconds))

    def save_lead(self, name, phone, query):
        unique_id = phone if phone != "N/A" else name
        if unique_id in self.existing_leads:
            logger.info(f"Duplicate: {name}. Skipping.")
            return

        file_exists = os.path.isfile(CSV_FILENAME)
        with open(CSV_FILENAME, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Business Name', 'Phone', 'Search Query', 'Timestamp'])
            writer.writerow([name, phone, query, time.strftime("%Y-%m-%d %H:%M:%S")])
            
        self.existing_leads.add(unique_id)
        logger.info(f"*** LEAD SAVED: {name} | {phone} ***")
        self.leads_found += 1

    def scroll_sidebar(self):
        try:
            scrollable_div = self.driver.find_element(By.CSS_SELECTOR, 'div[role="feed"]')
            self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollable_div)
            self.human_sleep(2, 4)
        except:
            pass

    def extract_data(self, query):
        logger.info("Starting extraction loop...")
        processed_indices = set()

        while self.checked_count < MAX_LEADS_TO_CHECK and not self.stop_requested:
            results = self.driver.find_elements(By.CSS_SELECTOR, RESULT_ITEM_SELECTOR)
            current_batch_count = len(results)
            found_new_in_batch = False

            for i in range(current_batch_count):
                if self.stop_requested: break
                if self.checked_count >= MAX_LEADS_TO_CHECK: break
                if i in processed_indices: continue
                
                found_new_in_batch = True
                processed_indices.add(i)
                self.checked_count += 1

                results = self.driver.find_elements(By.CSS_SELECTOR, RESULT_ITEM_SELECTOR)
                if i >= len(results): break 
                
                item = results[i]
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
                    self.human_sleep(1, 2)
                    item.click()
                    self.human_sleep(2, 4)
                    
                    # Name check
                    name = "Unknown"
                    try:
                        name = self.driver.find_element(By.CSS_SELECTOR, BUSINESS_NAME_SELECTOR).text.strip()
                    except: pass
                    
                    if name == "Unknown" or not name: continue

                    # Check Website
                    has_website = False
                    try:
                        WebDriverWait(self.driver, 2).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, WEBSITE_BUTTON_SELECTOR))
                        )
                        has_website = True
                    except: has_website = False

                    if not has_website:
                        logger.info(f"{name} is a VALID LEAD (No website).")
                        # Get Phone
                        phone = "N/A"
                        try:
                            phone_btn = self.driver.find_element(By.CSS_SELECTOR, PHONE_BUTTON_SELECTOR)
                            phone = phone_btn.get_attribute("aria-label") or phone_btn.text
                            phone = phone.replace("Phone: ", "")
                        except: pass 
                        self.save_lead(name, phone, query)
                    else:
                        logger.info(f"Skipping {name} (Has website).")

                except Exception as e:
                    logger.error(f"Error on item {i}: {e}")
                    continue
                
                self.human_sleep(1, 3)

            if not found_new_in_batch:
                self.scroll_sidebar()
                self.human_sleep(2, 3)
                new_results = self.driver.find_elements(By.CSS_SELECTOR, RESULT_ITEM_SELECTOR)
                if len(new_results) == current_batch_count:
                    break

    def run_search(self, niche, city, neighborhoods):
        self.stop_requested = False
        self.init_browser()
        
        locations = [n.strip() for n in neighborhoods.split(',')]
        if not locations or locations == ['']:
            locations = [city] # Fallback if no neighborhoods
        else:
            # Append city to neighborhoods for valid search
            locations = [f"{loc} {city}" for loc in locations]

        total_tasks = len(locations)
        
        try:
            for index, location in enumerate(locations):
                if self.stop_requested: break
                
                query = f"{niche} in {location}"
                logger.info(f"--- Search {index + 1}/{total_tasks}: {query} ---")
                
                search_url = f"https://www.google.com/maps/search/{query}"
                self.driver.get(search_url)
                self.human_sleep(5, 7)

                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, RESULT_ITEM_SELECTOR))
                    )
                    self.extract_data(query)
                except:
                    logger.info(f"No results for: {query}. Skipping.")

                if index < total_tasks - 1 and not self.stop_requested:
                    logger.info("cooling down (15s)...")
                    for _ in range(15):
                        if self.stop_requested: break
                        time.sleep(1)
        
        except Exception as e:
            logger.error(f"Error: {e}")
        finally:
            logger.info("Finished.")
            if self.driver:
                try: self.driver.quit()
                except: pass

class ClientFinderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ClientFinder Intelligence Tool")
        self.geometry("600x650")
        
        # Styles
        style = ttk.Style()
        style.theme_use('clam')
        
        # Main Frame
        main_frame = ttk.Frame(self, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(main_frame, text="ClientFinder Pro", font=("Helvetica", 16, "bold")).pack(pady=10)

        # Inputs
        input_frame = ttk.LabelFrame(main_frame, text="Search Configuration", padding="10")
        input_frame.pack(fill=tk.X, pady=5)

        ttk.Label(input_frame, text="Profession / Niche (e.g. Dentists):").pack(anchor=tk.W)
        self.niche_entry = ttk.Entry(input_frame)
        self.niche_entry.pack(fill=tk.X, pady=5)

        ttk.Label(input_frame, text="City (e.g. Asuncion):").pack(anchor=tk.W)
        self.city_entry = ttk.Entry(input_frame)
        self.city_entry.pack(fill=tk.X, pady=5)

        ttk.Label(input_frame, text="Neighborhoods (comma separated):").pack(anchor=tk.W)
        self.hood_text = scrolledtext.ScrolledText(input_frame, height=4, font=("Consolas", 9))
        self.hood_text.pack(fill=tk.X, pady=5)
        self.hood_text.insert(tk.END, "Villa Morra, Carmelitas, Centro") # Default

        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        
        self.start_btn = ttk.Button(btn_frame, text="Start Intelligence Agent", command=self.start_thread)
        self.start_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self.stop_scraper, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT, padx=5)

        # Log Window
        ttk.Label(main_frame, text="Live Intelligence Log:").pack(anchor=tk.W)
        self.log_area = scrolledtext.ScrolledText(main_frame, height=15, state='disabled', font=("Consolas", 8))
        self.log_area.pack(fill=tk.BOTH, expand=True)

        # Setup Logging
        text_handler = TextHandler(self.log_area)
        text_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S'))
        logger.addHandler(text_handler)
        
        self.finder = None

    def start_thread(self):
        niche = self.niche_entry.get().strip()
        city = self.city_entry.get().strip()
        hoods = self.hood_text.get("1.0", tk.END).strip()
        
        if not niche or not city:
            messagebox.showwarning("Input Error", "Please enter valid Niche and City.")
            return

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        self.finder = LeadFinder()
        
        # Run in separate thread to not freeze GUI
        t = threading.Thread(target=self.run_logic, args=(niche, city, hoods))
        t.daemon = True
        t.start()

    def run_logic(self, niche, city, hoods):
        try:
            self.finder.run_search(niche, city, hoods)
        except Exception as e:
            logger.error(f"Critical Error: {e}")
        finally:
            self.stop_btn.config(state=tk.DISABLED)
            self.start_btn.config(state=tk.NORMAL)

    def stop_scraper(self):
        if self.finder:
            logger.info("Stopping agent... (finishing current action)")
            self.finder.stop_requested = True

if __name__ == "__main__":
    app = ClientFinderApp()
    app.mainloop()
