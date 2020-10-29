import os
import csv
import argparse
from operator import itemgetter

DEFAULT_SAMPLE_FOLDERNAME = 'sample_data'

INCHES_TO_MM = 25.4

FILENAME_SISOFT_PADSTACKS = '_neutral_padstacks.csv'
FILENAME_SISOFT_PINS = '_neutral_pins.csv'
FILENAME_PCAD = '.PCB'
FILENAME_IDF = '.brd' 

def main(input_folder, refdes):
    converted_data = []
    converted_data_top_row = [
        'RefDes',
        'Netname',
        'TP X [mm]',
        'TP Y [mm]',
        'TP Diameter [mm]',

        'TP Type',
        'VPC Destination',
        'Probe Size',
        'Requirements'
    ]
    converted_data.append(converted_data_top_row)

    # create a list from the input "refdes" argument
    if ',' in refdes:
        refdes = refdes.split(',')


    sisoft_pins_valid, sisoft_padstacks_valid, idf_valid, pcad_valid = False, False, False, False
    filename_sisoft_pins, filename_sisoft_padstacks, filename_idf, filename_pcad = '','','',''
    board_name = ''
    for filename in os.listdir(input_folder):
        if FILENAME_SISOFT_PADSTACKS in filename:
            sisoft_padstacks_valid = True
            filename_sisoft_padstacks = os.path.join(input_folder, filename)

        if FILENAME_SISOFT_PINS in filename:
            sisoft_pins_valid = True
            filename_sisoft_pins = os.path.join(input_folder, filename)

        if FILENAME_IDF in filename:
            idf_valid = True
            filename_idf = os.path.join(input_folder, filename)
            board_name = filename[0:filename.rfind('.')]
        
        if FILENAME_PCAD in filename:
            pcad_valid = True
            filename_pcad = os.path.join(input_folder, filename)
            


    if not sisoft_pins_valid or not sisoft_padstacks_valid or not idf_valid or not pcad_valid:
        print('Necessary export files are missing, please re-export!')
        return
    
    padstacks = create_padstack_dict(filename_sisoft_padstacks)
    if not len(padstacks):
        print('No padstacks were extracted')
        return

    offset_x, offset_y = determine_offset(filename_idf, filename_pcad)

    try:
        # start reading the exported SiSoft file
        with open(filename_sisoft_pins, 'r') as csv_file:
            pins_reader = csv.DictReader(csv_file, delimiter=',')
            tp_number = 0
            for pins_row in pins_reader:
                row_refdes = pins_row.get('RefDes')
                try:
                    '''
                    The assignment to 'accept' is explained here:
                    1. Is "refdes" (argument input) a list or a single character?
                        -> Single Character: see if "row_refdes" is in "refdes", accept row data if true
                        -> List:
                                1. Make each array value "True" if "rd" (iterator value) is in both
                                    "refdes" and in "row_refdes"
                                2. Use "any" to determine "accept" based on any of the inputs are "True"
                    '''
                    accept = any(True for rd in refdes if rd in row_refdes) if (isinstance(refdes,list)) else (refdes in row_refdes)
                    if accept:
                        row_x, row_y = format_inch_coord(pins_row.get('X (in)')), format_inch_coord(pins_row.get('Y (in)'))
                        conv_x, conv_y = str( round(row_x - offset_x, 4) ), str( round(row_y - offset_y, 4) )
                        subckt = pins_row.get('Pin Number')
                        converted_data_row = [
                            row_refdes + '.' + subckt,                      # CONNECTOR.SUBCKT  (e.g. 'J1.2')
                            pins_row.get('CAD Net'),                        # NETNAME           (e.g. 'VCC_5V0')
                            conv_x,                                         # TP_X              (e.g. '12.23')
                            conv_y,                                         # TP_Y              (e.g. '4.25')
                            padstacks.get( pins_row.get('Padstack') ),      # TP_DIAMETER       (e.g. '1.4000')
                            
                            'Normal',       # TP Type [i.e. 'SMT', 'TH']
                            'TBD',          # VPC Destination
                            '100 mil'       # Probe Size
                            'None'          # Requirements [i.e. 'high current']
                        ]
                        converted_data.append(converted_data_row)
                        tp_number = tp_number + 1
                except:
                    print('Error converting ' + row_refdes)
                    pass

        # write the output file 
        output_path = os.path.join(input_folder, 'output_'+board_name+'_test-netlist.csv')
        csv.register_dialect('test_dialect', delimiter=';', quoting=csv.QUOTE_NONE)
        with open(output_path, 'w+', newline='') as output_file:
            writer = csv.writer(output_file, dialect='test_dialect')
            writer.writerows(converted_data) 
        
        print(f'Wrote {tp_number} test points to output!')

    except FileNotFoundError:
        print('unable to find necessary input file, please export data again')

def create_padstack_dict(padstacks_file: str):
    padstack_dict = {}
    try:
        padstacks_inputfile = csv.DictReader(open(padstacks_file))
    except:
        print('Failed to create padstack dict!')
        return None

    for line in padstacks_inputfile:
        padstack_number = line['Padstack']
        # Diameter if it's a Circluar padstack and the width if it's a rectangular padstack
        padstack_dim_mm = format_inch_coord(line['Width (in)']) if 'Rectangle' in line['Shape'] else format_inch_coord(line['Diameter (in)'])

        # IDF export data sometimes contains padstacks that are 0, ignore these...
        if float(padstack_dim_mm)>0.0:
            padstack_dict[padstack_number] = str(padstack_dim_mm)
            # print(f' adding pair {padstack_number}={padstack_dim}')

    return padstack_dict

'''
History:
    Method 1:
        SiSoft Data = OK
        IDF data = used through-hole PIN ECAD lines (i.e. .DRILLED_HOLES)
        Didn't work because TP's are surface mounted,
        and in general if there are no through-hole components
        then there are no lines with RefDes'es to tie dims with
    
    Method 2:
        SiSoft = Ok
        IDF data = Used .PLACEMENT
        Also didn't work because the coordinates were to components
            middle coordinate.

    Method 3:
        Use another output file (P-CAD ASCII) with the IDF ouput file.
        The P-CAD ASCII uses the same (though unknowingly defined) offset
            as the SiSoft data.
        However, unlike the SiSoft, P-CAD ASCII has information on the 
            Center location of a component.

'''
def determine_offset(filename_idf: str, filename_pcad: str):
    idf_centers = {}
    with open(filename_idf, 'r+') as idf_file:
        idf_line = idf_file.readline()
        while idf_line:
            # store the current lines position
            old_pos = idf_file.tell()
            # read the next line
            idf_line_next = idf_file.readline()
            # if the next line is a "dimension"-line...
            if any(keyword in idf_line_next for keyword in ['TOP', 'BOTTOM', 'PLACED']):
                '''
                idf_line
                    [0] = Package Name
                    [1] = Symbol Name
                    [2] = RefDes
                idf_next_line
                    [0] = X Center
                    [1] = Y Center
                    [2] = (Unknown)
                    [3] = Rotation
                    [4] = Layer
                    [5] = Placed / Not Placed
                '''
                # read out the refdes
                idf_line_refdes = idf_line[idf_line.rfind(' ')+1::].strip()
                # split out the "dimension"-line
                idf_line_dims = idf_line_next.split(' ')
                # store the x- and y-dimensions in a list under the refdes
                idf_centers[idf_line_refdes] = (idf_line_dims[0], idf_line_dims[1]) 


            idf_file.seek(old_pos)
            idf_line = idf_file.readline()
    
    pcad_centers = {}
    with open(filename_pcad, 'r') as pcad_file:
        for (line_cnt, pcad_line) in enumerate(pcad_file):
            if all(keyword in pcad_line for keyword in ['pattern', 'patternRef', 'refDesRef']):
                pcad_line_rdr = pcad_line[pcad_line.find('(refDesRef')::]       # "(refDesRef "########") (..."
                pcad_line_refdes = pcad_line_rdr[11:pcad_line_rdr.find(')')]    # 11 is lengeth of "(refDesRef "
                pcad_line_refdes = pcad_line_refdes.replace('"', '')            # remove quotes form refdes

                pcad_line_pt = pcad_line[pcad_line.find('(pt')::]       # "(pt {XXXX.XXXX}mm {YYYYY.YYYY}mm) (..."
                pcad_line_xy = pcad_line_pt[4:pcad_line_pt.find(')')]   # 4 is the length of "(pt ": Line is now "{YYYY.YYYY}mm {YYYY.YYYY}mm"
                pcad_line_xy = pcad_line_xy.replace('mm', '')           # remove "mm" from coordinates

                pcad_line_x, pcad_line_y = pcad_line_xy.split(' ')
                pcad_centers[pcad_line_refdes] = (pcad_line_x, pcad_line_y)

                if pcad_line_refdes in idf_centers:
                    break


    for idf_refdes, idf_coordpair in idf_centers.items():
        if idf_refdes in pcad_centers:
            idf_center_x, idf_center_y = idf_coordpair[0], idf_coordpair[1]
            pcad_center_x, pcad_center_y  = pcad_centers.get(idf_refdes)[0], pcad_centers.get(idf_refdes)[1]

            # offset_x, offset_y =
            return round( float(pcad_center_x) - float(idf_center_x) , 4), round( float(pcad_center_y) - float(idf_center_y), 4)

    return 0, 0 

def format_inch_coord(inch_coord_comma: float):
    inch_coord = inch_coord_comma.replace(',','.')
    return round(float(inch_coord)*INCHES_TO_MM, 4)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-folder', default=DEFAULT_SAMPLE_FOLDERNAME, help='Folder with SiSoft and IDF export files.')
    parser.add_argument('--refdes', default='', help='Enter which RefDes\'es should be extracted (e.g. J, T, TP). Multiple RefDes\'es can be defined, by separating them with a comma, i.e. --refdes=J,TP', required=True)
    args = parser.parse_args()
    try:
        main(args.input_folder, args.refdes)
    except:
        print('Failed to generate output file.')
        pass