# Omaha - Owensboro Music and Hymnal Application

# 2026-01-03 wph Initial use in services
# 2026-01-04 wph increased Burst Delay from 0.005 sec to 0.075 sec. Enabled tailscale, changed from multicast to point-to-point UDP messaging.
# 2026-01-12 wph Changed to use local ips and point to point UPD messages.
# 2026-01-14 wph Added md5 and omaha-peers.json file in Owensboro Music folder so it will be updated with weekly file updates.

import os
import sys
import subprocess
import datetime
import re
import select
import json
from pathlib import Path
from pypdf import PdfReader
import socket
import struct
import time

COMM_PORT = 5007
SETTINGS_FILE = Path.home() / "omaha" / "config" /"omaha.json"
OMAHA_PEERS_FILE = Path.home() / "omaha" / "data" / "OwensboroMusic" / "omaha-peers.json"
peer_hostnames=''
saved_instrument='Hymnal'
saved_orientation='wide'
leader_mode = {}
LeaderCode = 1
FollowerCode = 2
IndependentCode = 3
leader_mode[1] = 'leader'
leader_mode[2] = 'follower'
leader_mode[3] = 'independent'
saved_leader_mode=2

def get_owensboro_music_dir():
    """Returns the path to the 'OwensboroMusic' directory."""
    home_dir = Path.home()
    music_dir = home_dir / "omaha" / "data" / "OwensboroMusic"
    if not music_dir.is_dir():
        print(f"Error: Directory not found at {music_dir}")
        exit()
    return music_dir

def list_music_files(directory):
    """Lists all files in the directory and attempts to parse a date from the filename."""
    files_with_dates = []
    date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")
    instrument_pattern = re.compile(rf"^{saved_instrument}")
    orientation_pattern = re.compile(rf"-{saved_orientation}\.pdf")
    for file_path in sorted(directory.iterdir()):
        if file_path.is_file():
            match = date_pattern.search(file_path.name)
            file_date = datetime.date.min
            if match:
                try:
                    file_date = datetime.datetime.strptime(match.group(1), "%Y-%m-%d").date()
                except ValueError:
                    continue
            if instrument_pattern.search(file_path.name) and orientation_pattern.search(file_path.name):
                files_with_dates.append((file_path, file_date))
    return files_with_dates

def find_default_file(files_with_dates):
    """Finds today's file, or the closest future file."""
    today = datetime.date.today()
    today_file = None
    closest_future_file = None
    min_diff = datetime.timedelta(days=99999)

    for file_path, file_date in files_with_dates:
        if file_date == today:
            today_file = file_path
            break
        elif file_date > today:
            diff = file_date - today
            if diff < min_diff:
                min_diff = diff
                closest_future_file = file_path
    
    return today_file or closest_future_file

def read_file_prefixes():
    """Returns list of unique file prefixes"""
    pattern = re.compile(r"^([a-zA-Z]*)[0-9]*.*$")
    prefixes = set()
    for filename in os.listdir('./data/OwensboroMusic/.'):
        #print(f"filename = {filename}")
        match = pattern.match(filename)
        if match:
            #print(f"pattern matched = {match.group(1)}")
            prefix = match.group(1)
            prefixes.add(prefix)
    #print(f"prfixes = {prefixes}")
    return list(prefixes)

def save_settings(leader_mode, instrument,orientation):
    """Save settings to SETTINGS_FILE"""
    #print(f"Attempting to save to: {os.path.abspath(SETTINGS_FILE)}")
    settings = {
        'leader_mode': leader_mode,
        'instrument': instrument,
        'orientation': orientation
    }
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
            #print(f"settings have been saved")
    except IOError as e:
        print(f"Error saving settings: {e}")

def save_peers(peers):
    """Save list of peer hostnames to OMAHA_PEERS_FILE"""
    try:
        with open(OMAHA_PEERS_FILE, 'w') as f:
            json.dump(peers, f, indent=4)
    except IOError as e:
        print(f"Error saving peers file: {e}")

def read_peers():
    """Returns list of hostnames of omaha peers from OMAHA_PEERS_FILE"""
    with open(OMAHA_PEERS_FILE, 'r') as f:
        return json.load(f)

def select_instrument():
    """Displays the menu of instruments and get user input (only numpad numbers)."""
    print()
    print("Select an instrument (file prefix):")
    instruments = read_file_prefixes()
    i=0
    while i < len(instruments):
        print(f"   {i}:  {instruments[i]}")
        i = i + 1
    print("\nEnter the number of the instrument you want to play")
    while True:
        choice=input()
        try:
            choice_index = int(choice)
            if 0 <= choice_index < len(instruments):
                #print(f"returning {instruments[choice_index]}")
                return instruments[choice_index]
        except ValueError:
            continue

def select_leader_mode():
    while True:
        print()
        print("Select a leader_mode:")
        print("1. Leader (there should be no more than 1 leader or followers will try to follow all of them)")
        print("2. Follower - you will automatically be set to the same song as the leader (the default setting)")
        print("3. Independent - you will need to make all page changes")
        choice=input()
        try:
            choice_index = int(choice)
            if 1<= choice_index <= 3:
                return choice_index
        except ValueError:
            continue

def display_hymnal_alphabetical_index(choice):
    index_section = {}
    index_section[1] = re.compile(r"^[as][0-9]{3}\s*[AB]")
    index_section[2] = re.compile(r"^[as][0-9]{3}\s*[CDEF]")
    index_section[3] = re.compile(r"^[as][0-9]{3}\s*[GH]")
    index_section[4] = re.compile(r"^[as][0-9]{3}\s*[IJ]")
    index_section[5] = re.compile(r"^[as][0-9]{3}\s*[KLMN]")
    index_section[6] = re.compile(r"^[as][0-9]{3}\s*[OPQ]")
    index_section[7] = re.compile(r"^[as][0-9]{3}\s*[RS]")
    index_section[8] = re.compile(r"^[as][0-9]{3}\s*[T]")
    index_section[9] = re.compile(r"^[as][0-9]{3}\s*[UVWXYZ]")
    
    # find the filenames that match the selection
    matching_files = []
    directory_path = f"./data/Hymnals/{saved_instrument}"
    try:
        for filename in os.listdir(directory_path):
            #print(f"checking <{filename}> to see if it matches")
            if index_section[int(choice)].match(filename):
                matching_files.append(filename)
    except FileNotFoundError:
        print(f"Error: The directory '{directory_path}' was not found.")
        return
    
    matching_files.sort(key=lambda filename: filename[5:])
    
    # format the matching filenames for display
    COLUMN_WIDTH = 40
    num_files = len(matching_files)
    NUM_COLUMNS = 3
    
    num_rows = int(num_files / NUM_COLUMNS)
    if num_rows*NUM_COLUMNS < num_files:
        num_rows += 1
    
    for i in range(num_rows):
        row_output = ""
        for col in range(NUM_COLUMNS):
            file_index = i + col * num_rows
            
            if file_index < num_files:
                filename = matching_files[file_index]
                formatted_filename = filename.replace('a','0',1)
                formatted_filename, extension = os.path.splitext(formatted_filename)
                truncated_filename = formatted_filename[:COLUMN_WIDTH].ljust(COLUMN_WIDTH)
                row_output += truncated_filename
            else:
                # Add padding for empty spots if the columns are uneven
                row_output += " " * COLUMN_WIDTH
        print(row_output.rstrip())
    return

def find_matching_file(choice_number_string, directory_path):
    """
    Finds the first file starting with 'a' + a 3-digit number (equal to choice_number_string) 
    followed by a space and other characters, and returns the full Path object.
    """
    
    # 1. Pad the choice string with leading zeros
    padded_number = f"{int(choice_number_string):03d}"
    print(f"Searching for files matching number: {padded_number}")

    # 2. Create the precise regular expression pattern
    pattern = re.compile(rf"^a{padded_number} .+$")

    # 3. Iterate through files in the specified directory
    for filename in os.listdir(directory_path):
        if pattern.match(filename):
            # Return the full, complete Path object
            return Path(directory_path) / filename
            
    # If the loop finishes without finding a file, return None
    return None

def rotate_screen(orientation):
    # orientation = 'normal' | '90' clockwise | '180' | '270' 
    output_name = "HDMI-A-1" # run 'wlr-randr' in a terminal to see the correct name
    try:
        subprocess.run(["wlr-randr", "--output", output_name, "--transform", orientation],check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error rotating screen: {e}")

def display_menu(files_with_dates, default_file,sock):
    """Displays the menu and gets user input (only numpad numbers)."""
    global saved_orientation
    global saved_instrument
    global saved_leader_mode
    
    while True:
        print("Press Enter to proceed.")
        input()
        subprocess.run(["clear"])
        subprocess.run(["md5sum",os.path.basename(sys.argv[0])])
        # ANSI escape code for green text
        GREEN = "\033[92m"
        RESET = "\033[0m"
        menu_file = []
        print(f"{GREEN}")
        print("\nOwensboro Music Weekly Files:")
        for i, (file_path, file_date) in enumerate(files_with_dates):
            prefix = " > " if file_path == default_file else "   "
            date_str = file_date.isoformat() if file_date != datetime.date.min else "No date"
            print(f"{prefix}{i+1}: {file_path.name}")
        if saved_orientation != "tall":
            print()
            print("Index to Hymns:                          Settings and Utilitis:")
            print(f"  01:  A or B                              95: change leader mode from {RESET}{leader_mode[saved_leader_mode]}{GREEN}")
            print(f"  02:  C, D, E, or F                       96: change orientation from {RESET}{saved_orientation}{GREEN}")
            print(f"  03:  G or H                              97: change intrument from {RESET}{saved_instrument}{GREEN}")
            print(f"  04:  I or J                              98: reload Hymnals files from dropbox")
            print(f"  05:  K, L, M, or N                       99: reload Weekly files from dropbox")
            print(f"  06:  O, P, or Q                          /1: shutdown now")
            print(f"  07:  R or S")
            print(f"  08:  T")
            print(f"  09:  U, V, W, X, Y, or Z")
            print(f"0xyz: to open SDA 1985 hymn number xyz")
        else:
            print()
            print("Index to Hymns:       ")
            print(f"  01:  A or B        ")
            print(f"  02:  C, D, E, or F ")
            print(f"  03:  G or H        ")
            print(f"  04:  I or J        ")
            print(f"  05:  K, L, M, or N ")
            print(f"  06:  O, P, or Q")
            print(f"  07:  R or S")
            print(f"  08:  T")
            print(f"  09:  U, V, W, X, Y, or Z")
            print(f"0xyz: to open SDA 1985 hymn number xyz")
            print()
            print("Settings and Utilitis:")
            print(f"   95: change leader mode from {RESET}{leader_mode[saved_leader_mode]}{GREEN}")
            print(f"   96: change orientation from {RESET}{saved_orientation}{GREEN}")
            print(f"   97: change intrument from {RESET}{saved_instrument}{GREEN}")
            print(f"   98: reload Hymnals files from dropbox")
            print(f"   99: reload Weekly files from dropbox")
            print(f"   /1: shutdown now")
            print()           
        print(f"\nEnter the number of a menu option:")
        
        choice=input()
        if "/1" == choice:
            subprocess.run(["sudo","shutdown","now"])
            return
        try:
            choice_index = int(choice) - 1
            if not(choice.startswith("0")) and (0 <= choice_index < len(files_with_dates)):
                return files_with_dates[choice_index][0]
            else:
                if choice.startswith("0") and (1<=int(choice)<=9):
                        display_hymnal_alphabetical_index(int(choice))
                        choice = input()
                        matching_file = find_matching_file(choice, f"./data/Hymnals/{saved_instrument}")
                        if matching_file:
                            open_with_impressive(matching_file,sock)
                            return
                        else:
                            print("hymn number not found")
                            input("")
                            return
                elif "99" == choice:
			# call utility to re-fresh files from dropbox
                        subprocess.run(["./UpdateWeeklyFiles.sh"])
                        return
                elif "95" == choice:
                        saved_leader_mode = select_leader_mode()
                        save_settings(saved_leader_mode, saved_instrument,saved_orientation)
                elif "96" == choice:
                        if saved_orientation == "wide":
                            saved_orientation = 'tall'
                            rotate_screen("270")
                        else:
                            rotate_screen("normal")
                            saved_orientation = 'wide'
                        print(f"saved_orientation = {RESET}{saved_orientation}{GREEN}")
                        save_settings(saved_leader_mode, saved_instrument,saved_orientation)
                        return
                elif "97" == choice:
                        saved_instrument = select_instrument()
                        print(f"saved_instrument = {RESET}{saved_instrument}{GREEN}")
                        save_settings(saved_leader_mode, saved_instrument,saved_orientation)
                        return
                elif "98" == choice:
                        subprocess.run(["./UpdateHymnalsFiles.sh"])
                        return
                else:
                    if '0' == choice[0]:
                        # look for a matching hymn file.
                        matching_file = find_matching_file(choice, f"./data/Hymnals/{saved_instrument}")
                        if matching_file:
                            open_with_impressive(matching_file,sock)
                            return
                        else:
                            print("Hymn number not found. Press Enter to continue.")
                            input("")
                            return
                    else:
                        print(f"Did you supply {choice}? Invalid number. Please choose from the list.")
                        input("Press Enter to continue.")
        except ValueError:
            print("Invalid input.")
    # ANSI escape code to reset green text
    print(f"{RESET}")

def get_ip_with_timeout(hostname, timeout_sec=0.5):
    try:
        # getaddrinfo is more robust than gethostbyname and supports timeouts
        # We look for IPv4 addresses (AF_INET)
        results = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        
        # We just need the first IP address returned
        return results[0][4][0] 
        
    except socket.gaierror:
        # Hostname not known
        return None
    except socket.timeout:
        # Lookup took longer than timeout_sec
        print(f"Timeout resolving {hostname}")
        return None

def get_local_omaha_peers():
    device_list = []

    for name in peer_hostnames:
        # Try resolving the name with a 0.5 second timeout
        ip = get_ip_with_timeout(name, timeout_sec=0.5)
        if ip:
            device_list.append(ip)
            
    return device_list

def get_tailscale_peers():
    try:
        result = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        peers = data.get('Peer', {})
        device_list = []
        for details in peers.values():
            # Filter: 1. Must be Online, 2. Must have 'omaha' in the name
            if details.get('Online') and 'omaha' in details.get('HostName','').lower():
                # Get the first IPv4 address (usually starts with 100.)
                ips = details.get('TailscaleIPs', [])
                if ips:
                    device_list.append(ips[0])
        return device_list
    except:
        return []

def open_with_impressive(file_path,sock):
    """Opens the file with impressive with specified key bindings."""
    PresentationItemArray = []
    PageNumberDict = {}
    
    # Define milestones for when the current page should be re-sent by the leader (in seconds). The final entry is the maximum interval dealy
    milestones = [0.075, 0.150, 1, 5] 
    MilestoneNextIndex = -1 # this value means the first page has not been sent so the timer has not yet started.
    
    #build index of ProgramItem to PageNumber and of PageNumber to ProgramItem        
    try:
        reader = PdfReader(file_path)
        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text().strip()
            print(f"extracted:<{text}>")
            match = re.search(r":\s*(.*?)\n(.*?)\n(.*?[A-Z][a-z]{2}-\d\d-\d\d\d\d)", text,re.MULTILINE | re.DOTALL)
            if match:
                #hex_codes = " ".join(f"{ord(c):02X}" for c in match.group(1).strip())
                #print(hex_codes)
                item = match.group(1).strip() + " " + match.group(3).strip()
                print(f"page {page_num} is <{item}>")
                PresentationItemArray.append(item)
                
                #Dictionary stores {item: first page found}
                if item not in PageNumberDict:
                    PageNumberDict[item] = page_num
            else:
                print(f"no match found for page {page_num}")
                PresentationItemArray.append(None)
    except Exception as e:
        print(f"Error: {e}")

    print(f"\nOpening {file_path.name} in Impressive.")
    print("Use '/' to close the presentation and return to the menu.")
    print("Use '+' for next page, '-' for previous page, '*' for fade-to-black.")
    
    try:
        # set tall_switch to run impressive with rotation if the file name contains "-tall.pdf"
        if "-tall.pdf" in file_path.name:
            tall_switch = "-g 1080x1920"  # before I changed the orientation in lxterminal, I used "-r 1".
        else:
            tall_switch = "-r 0"
            
        # run impressive
        # use -u for unbuffered binary output to avoid internal Python buffering
        cmd = [sys.executable, "-u", "./bin/impressive", "--controls", "./config/impressive_E","-T 0",tall_switch,str(file_path)]
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1
        )
        try:
            # wait for impressive to load the first page
            loaded=0
            while loaded==0:
                output = process.stdout.readline()
                if output:
                    print(f"Impressive says: <{output.strip()}>")
                    match = re.match(r"PageEntered=(\d*)", output)
                    if match:
                        myCurrentPage = int(match.group(1))
                        loaded=1
                    
            # define the list of inputs to monitor
            inputs = [process.stdout,sock]
            while True:
                # Check if the process has already died before waiting
                if process.poll() is not None:
                    # process has exited
                    break
                
                # Check if it is time to resend the current page
                if MilestoneNextIndex>-1:
                    MilestoneElapsed = time.monotonic() - MilestoneStartTime
                    if MilestoneElapsed >= milestones[MilestoneNextIndex]:
                        send_page(sock,CurrentPageText)
                        if MilestoneNextIndex < len(milestones) -1:
                            MilestoneNextIndex += 1
                        else:
                            # Restart the timer to wait the duration specified in the final milestones value.
                            MilestoneStartTime = time.monotonic()
                        
                readable, _, _ = select.select(inputs,[],[],0.1)
                for source in readable:
                    print("Found source in readable")
                    if (source is process.stdout):
                        # Handle local user page changes from Impressive
                        match = re.search(r"PageEntered=(\d+)",process.stdout.readline())
                        if match:
                            myCurrentPage = int(match.group(1))
                            try:
                                print(f"Now on page {myCurrentPage} ",end="")
                                print(f"Entering {PresentationItemArray[myCurrentPage-1]}")
                            except IndexError:
                                process.terminate()
                                process.wait()
                                return
                            
                        if match and (LeaderCode==saved_leader_mode):
                            print(f"Impressive moved to page: <{match.group(1)}> = <{PresentationItemArray[int(match.group(1))-1]}>")
                            # notify followers of a page change
                            CurrentPageText = PresentationItemArray[int(match.group(1))-1]
                            send_page(sock,CurrentPageText)
                            
                            # set the starting time for milestone re-transmissions.
                            MilestoneStartTime = time.monotonic()
                            MilestoneNextIndex = 0
                            
                    elif (source.fileno() is sock.fileno()):
                        print("source is sock")
                        # Handle remote leader page changes from the network
                        data, addr = sock.recvfrom(1024)
                        if data:
                            print(f"Remote sync received from {addr}: <{data.decode()}> ",end="")
                            LeaderPageNumber = PageNumberDict.get(data.decode())
                            if ((FollowerCode==saved_leader_mode) and (LeaderPageNumber is not None)):
                                if (PresentationItemArray[myCurrentPage-1] != data.decode()):                            
                                    # only change the page if the leader is on a different song.
                                    process.stdin.write(f"{LeaderPageNumber}\n")
                                    process.stdin.flush()
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")
        finally:
            process.terminate()
            process.wait()
    except FileNotFoundError:
        print("Error: 'impressive' command not found. Please ensure it is installed and in your system PATH.")

def send_page(sock, page_txt):
    # Leader sends to the followers
    targets = get_local_omaha_peers()
    if not targets:
        return # No one to send to
        
    # Create a TEMPORARY socket for sending only. 
    # Do NOT bind it. The OS will assign a random source port.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender_sock:
        message_bytes = str(page_txt).encode('utf-8')
        for ip in targets:
            try:
                sender_sock.sendto(message_bytes, (ip, COMM_PORT))
                print(f"Sent to {ip}, message = {page_txt}")
            except Exception as e:
                print(f"Error sending to {ip}: {e}")
    
def main():
    global saved_leader_mode, saved_instrument, saved_orientation, peer_hostnames
    
    # Read the settings file
    #print(f"Attempting to read from: {os.path.abspath(SETTINGS_FILE)}")
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                saved_leader_mode = settings.get('leader_mode')
                saved_instrument = settings.get('instrument')
                saved_orientation = settings.get('orientation')
        except:
            print("Settings could not be loaded.")
    else:
        saved_leader_mode = FollowerCode # 1=leader, 2=follower, 3=independent
        saved_instrument = 'Hymnal'
        saved_orientation = 'wide'
        
    # set screen orientation to match saved value
    if saved_orientation == "wide":
        rotate_screen("normal")
    else:
        rotate_screen("270")

    # Read the list of omaha hostnames from the file
    peer_hostnames = read_peers()

    # Setup Socket for leader/follower
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT,1)
    except AttributeError:
        pass # Some systems don't support SO_REUSEPORT
    # Bind to ALL interfaces so it can hear traffic from the physical Wi-Fi and Tailscale
    sock.bind(('',COMM_PORT))

    while True:
        music_dir = get_owensboro_music_dir()
        files = list_music_files(music_dir)
        if not files:
            print("No music files found.")
            break
        
        default_file = find_default_file(files)
        selected_file = display_menu(files, default_file, sock)
        
        if selected_file:
            open_with_impressive(selected_file, sock)


if __name__ == "__main__":
    main()
