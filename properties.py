import re, requests, os, datetime
import pyopenms as oms
from pyopenms import MSExperiment, MzXMLFile
import xml.etree.ElementTree as ET
from molmass import Formula
import urllib.parse
from google.cloud import storage

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'key.json'
storage_client = storage.Client()
bucket = storage_client.bucket("mzxmlfiles")
storage.blob._DEFAULT_CHUNKSIZE = 5 * 1024 * 1024  
storage.blob._MAX_MULTIPART_SIZE = 5 * 1024 * 1024  

# Checks for file extension - extra protocol
ALLOWED_EXTENSIONS = {"mzxml"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# def upload_to_bucket(blob_name, file_path):
#     blob = bucket.blob(blob_name)
#     blob.upload_from_string(file_path)
#     #blob.upload_from_filename(file_path)

def download_file_uri(uri, filename):
    f = open("./files/" + filename, "a")
    f.close()
    with open("./files/" + filename, 'wb') as f:
        storage_client.download_blob_to_file(uri, f)
    return "./files/" + filename

def generate_upload_signed_url_v4(blob_name):
    """Generates a v4 signed URL for uploading a blob using HTTP PUT.

    Note that this method requires a service account key file. You can not use
    this if you are using Application Default Credentials from Google Compute
    Engine or from the Google Cloud SDK.
    """
    # bucket_name = 'your-bucket-name'
    # blob_name = 'your-object-name'

    blob = bucket.blob(blob_name)

    url = blob.generate_signed_url(
        version="v4",
        # This URL is valid for 15 minutes
        expiration=datetime.timedelta(minutes=15),
        # Allow PUT requests using this URL.
        method="PUT",
        content_type="application/octet-stream",
    )
    return url

def sendCURL(url, data, filename):

    query_string = url.split("?")[1]
    params_list = query_string.split("&")

    headers = [
        "X-Goog-Algorithm",
        "X-Goog-Credential",
        "X-Goog-Date",
        "X-Goog-Expires",
        "X-Goog-SignedHeaders",
        "X-Goog-Signature",
    ]

    params = {}

    for param in params_list:
        for header in headers:
            if param.startswith(header):
                start_index = len(header) + 1
                value = param[start_index:]
                decoded_value = urllib.parse.unquote(value)
                params[header] = decoded_value

    headers = {
        'Content-Type': 'application/octet-stream',
    }
    response = requests.put('https://storage.googleapis.com/mzxmlfiles/' + filename, params=params, headers=headers, data=data)


# Table Header Function
def create_header(mzxml_file):
    with open(mzxml_file) as f:
        for line in f:
            if ("<scan") in line:
                input_text = line

                # Locate the start and end positions of the properties
                start_position = input_text.find("scan") + len("scan")
                end_position = input_text.find(">")

                # Extract the properties substring from input_text
                properties_substring = input_text[start_position:end_position].strip()

                # Split properties_substring into individual properties
                properties_list = properties_substring.split(" ")

                # Extract the headers (keys) from the properties
                headers = []
                for prop in properties_list:
                    key, _ = prop.split("=", 1)
                    headers.append(key)
    return headers


# Extract and Create Table Body Function
def create_body(mzxml_file):
    scan_list = []
    with open(mzxml_file) as f:
        for line in f:
            if ("<scan") in line:
                input_text = line

                # Locate the start and end positions of the properties
                start_position = input_text.find("scan") + len("scan")
                end_position = input_text.find(">")

                # Extract the properties substring from input_text
                properties_substring = input_text[start_position:end_position].strip()

                # Split properties_substring into individual properties
                properties_list = properties_substring.split(" ")

                # Parse the properties into a dictionary
                properties_dict = {}
                for prop in properties_list:
                    key, value = prop.split("=", 1)
                    properties_dict[key] = value.strip('"')

                # Append properties_dict to the scan_list
                scan_list.append(properties_dict)
    return scan_list


# Metadata
def parse_attribute(tag_string):
    attribs = {}
    tag_parts = re.findall(r'(\S+)=("[^"]*"|\'[^\']*\')', tag_string)
    for name, value in tag_parts:
        value = value.strip('"').strip("'")
        attribs[name] = value
    return attribs


def parse_ms_instrument(xml_file):
    with open(xml_file, "r") as file:
        content = file.read()

    start_ms_instrument = content.find("<msInstrument>") + len("<msInstrument>")
    end_ms_instrument = content.find("</msInstrument>")
    ms_instrument_content = content[start_ms_instrument:end_ms_instrument]

    lst = []
    ms_instrument = {}
    while True:
        start_tag = ms_instrument_content.find("<") + 1
        end_tag = ms_instrument_content.find(">")
        if start_tag == 0 or end_tag == -1:
            break

        open_tag = ms_instrument_content[start_tag:end_tag]
        if " " not in open_tag:
            # Empty tag, skip
            ms_instrument_content = ms_instrument_content[end_tag + 1 :]
            continue

        close_tag = open_tag.split()[0]
        start_close_tag = ms_instrument_content.find("</" + close_tag + ">") + len(
            "</" + close_tag + ">"
        )
        ms_instrument_content = ms_instrument_content[start_close_tag:]

        attribs = parse_attribute(open_tag)
        ms_instrument[close_tag] = attribs
    return ms_instrument


# Scan Count
def extract_scan_count(mzxml_file):
    with open(mzxml_file, "r") as file:
        for line in file:
            if "scanCount" in line:
                start = line.index("scanCount=") + 11
                end = line.index('"', start)
                return int(line[start:end])
    return None


# Get peaks
def detect_peaks(file_path, scan_num):
    lst = []
    # Load the mzXML file
    exp = oms.MSExperiment()
    oms.MzXMLFile().load(file_path, exp)

    # Initialize the peak picker
    picker = oms.PeakPickerHiRes()

    # Perform peak picking
    picked_exp = oms.MSExperiment()
    picker.pickExperiment(exp, picked_exp)

    for spectrum in picked_exp:
        current_scan_num = spectrum.getNativeID()
        if current_scan_num.lstrip("scan=") == str(scan_num):
            for peak in spectrum:
                mz = peak.getMZ()
                intensity = peak.getIntensity()
                lst.append({current_scan_num: [mz, intensity]})
    return lst


def searchCompound(mz):
    url = "https://pubchem.cheminfo.org/mfs/em?em=" + str(mz)

    wow = requests.get(url)
    result = wow.content
    result = result.decode("UTF-8")

    string_to_search = str(result)
    start_index = string_to_search.index('"_id":"') + len('"_id":"')
    end_index = start_index
    for i in range(start_index, len(string_to_search)):
        if string_to_search[i] == '"':
            end_index = i
            break
    desired_string = string_to_search[start_index:end_index]
    return desired_string


def findCompound(mz):
    try:
        return searchCompound(mz)
    except ValueError:
        return "Compound not found"


def defCompound(formula):
    url = "https://pubchem.cheminfo.org/molecules/mf?mf=" + str(formula)
    wow = requests.get(url)
    temp = wow.content
    temp = temp.decode("UTF-8")
    start_index = temp.find("iupac")
    # Find the index of the closing double quotes after "iupac"
    end_index = temp.find('"', start_index + 8)
    # Extract the substring between start_index and end_index
    result = temp[start_index + 8 : end_index]

    if result == "ull," or result == "t":
        return "No formal name/Compound not found"
    else:
        return result


def composition(formula):
    if (formula == "Compound not found"):
        return "Unknown/Compound not found"
    f = Formula(formula)
    return f.composition()


def remove_namespace(tag):
    return tag.split("}")[-1]


def mzxml_to_xml(mzxml_file, xml_file):
    # Parse the mzXML file
    tree = ET.parse(mzxml_file)
    root = tree.getroot()

    # Create a new XML root element
    new_root = ET.Element(remove_namespace(root.tag))

    # Iterate through the mzXML elements and copy them to the new XML file
    for element in root:
        new_element = ET.SubElement(new_root, remove_namespace(element.tag))

        for attr_key, attr_value in element.attrib.items():
            new_element.set(attr_key, attr_value)

        for child in element:
            new_child = ET.SubElement(new_element, remove_namespace(child.tag))

            for child_attr_key, child_attr_value in child.attrib.items():
                new_child.set(child_attr_key, child_attr_value)

    # Write the new XML file
    new_tree = ET.ElementTree(new_root)
    new_tree.write(xml_file, encoding="utf-8", xml_declaration=True)
