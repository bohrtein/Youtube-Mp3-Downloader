import os

def Print_Tag(message, tag="System") -> None:
    """
    Outputs a consistently formatted log message to the terminal.
    
    The tag is encased in brackets and centered within a fixed 14-character 
    width to ensure that messages align vertically regardless of tag length.
    
    Args:
        message (str): The primary text to be displayed.
        tag (str): The category label (e.g., 'Success', 'Error', 'Process'). 
                   Defaults to 'System'.
    """
    # Using f-string alignment: ^14 means "center within 14 spaces"
    formatted_tag = f"[{tag:^14}]"
    print(f"{formatted_tag} {message}")

class interfaceComponents:
    """
    A container class for managing UI state and shared interface references.
    """
    def __init__(self):
        # Placeholder for potential future extension or specific print tracking
        self.print001 = None
        
def header_start():
    """
    Prints the application title card to the console. 
    Used during script initialization to provide visual context to the user.
    """
    print("=======================================")    
    print("   YouTube Playlist Downloader (FLAC)  ")
    print("=======================================") 

def header_exit():
    """
    Displays a graceful exit message and credit.
    
    Includes a blocking input() call to prevent the terminal window 
    from closing instantly if the script is run as an executable.
    """
    print("Thank you for using the program")
    print("Made by bohrtein")
    input("Press Enter to close...")