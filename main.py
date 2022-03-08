import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
import time
import configparser
import os
import logging
import numpy as np
import nidaqmx
import nidaqmx.constants as const
from spinapi import *

channel_num = 24 # number of TTL output channels of SpinCore PulseBlasterUSB
button_color = 'white'
bgcolorlist = ['lavender', 'honeydew'] # TTL output channel background color
duration_unit = ["ms", "us", "ns"]
opcodes = ["CONTINUE", "STOP", "LOOP", "END_LOOP", "JSR", "RTS", "BRANCH", "LONG_DELAY", "WAIT"]

class newCombobox(ttk.Combobox):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.unbind_class("TCombobox", "<MouseWheel>")

# the first column of this GUI, which are mainly descriptive labels
class Descr(tk.LabelFrame):
    def __init__(self, master=None):
        super().__init__(master)
        self.configure(relief='flat', borderwidth=0, highlightthickness=0)
        self.place_duration()
        self.place_note()
        self.place_channels()
        self.place_opcode()
        self.place_opdata()
        self.place_instrnum()

    def place_duration(self):
        self.du = tk.Label(self, text='Duration:')
        self.du.grid(row=0, column=1, padx=0, ipady=1)

    def place_note(self):
        self.un = tk.Label(self, text='Note:')
        self.un.grid(row=1, column=1, padx=0, ipady=1)

    def place_channels(self):
        self.ch_label_list = []
        for i in range(channel_num):
            bgcolor = bgcolorlist[i%2]
            ch_label = tk.Entry(self, width=20)
            ch_label.grid(row=2+i, column=0, padx=8, sticky='e')
            self.ch_label_list.append(ch_label)
            self.ch = tk.Label(self, text='Channel '+str(i), bg=bgcolor, anchor="center")
            self.ch.grid(row=2+i, column=1, ipady=2, sticky='news')

    def place_opcode(self):
        self.opc = tk.Label(self, text='Op code:')
        self.opc.grid(row=channel_num+2, column=1)

    def place_opdata(self):
        self.opd = tk.Label(self, text='Op data:')
        self.opd.grid(row=channel_num+3, column=1)

    def place_instrnum(self):
        self.ins = tk.Label(self, text='Instruction #:')
        self.ins.grid(row=channel_num+4, column=1)

    def compile_ch_label_text(self):
        self.ch_label_text = []
        for i in reversed(range(channel_num)):
            self.ch_label_text.append(self.ch_label_list[i].get())


# the 2rd to nth column of this gui, which are instruction data that will be pased to PulseBlasterUSB
class Instr(tk.LabelFrame):
    def __init__(self, master, instr_num):
        super().__init__(master)
        self.configure(relief='flat', borderwidth=0, highlightthickness=0)
        self.instr_num = instr_num
        self.place_duration()
        self.place_note()
        self.place_checkboxes()
        self.place_opcode()
        self.place_opdata()
        self.place_instrnum()

    def place_duration(self):
        label_frame = tk.LabelFrame(self, width=9, relief='flat')
        label_frame.grid(row=0, column=0, padx=0)
        self.du = tk.Entry(label_frame, width=6)
        self.du.insert(0, "10")
        self.du.grid(row=0, column=0, padx=0)
        self.un = newCombobox(label_frame, values=duration_unit, width=3, state="readonly")
        self.un.grid(row=0, column=1, padx=0)
        self.un.current(0)

    def place_note(self):
        self.note = tk.Entry(self, width=12)
        self.note.grid(row=1, column=0)

    def place_checkboxes(self):
        self.cbvarlist = []
        self.cblist = []
        for i in range(channel_num):
            bgcolor = bgcolorlist[i%2]
            self.cbvarlist.append(tk.IntVar())
            self.cblist.append(tk.Checkbutton(self, bg=bgcolor, anchor="center", variable=self.cbvarlist[i]))
            self.cblist[i].grid(row=i+2, column=0, padx=0, pady=0, sticky='news')

    def place_opcode(self):
        self.opc = newCombobox(self, values=opcodes, width=10, state="readonly")
        self.opc.grid(row=channel_num+2, column=0, padx=8, sticky="news")
        self.opc.current(0)

    def place_opdata(self):
        self.opd = tk.Entry(self, width=2)
        self.opd.grid(row=channel_num+3, column=0)
        self.opd.insert(0, "0")

    def place_instrnum(self):
        self.ins = tk.Label(self, text=str(self.instr_num))
        self.ins.grid(row=channel_num+4, column=0)

    def compile_instr(self):
        # collect user defined values and compile tham as a list, it will later be passed to PulseBlaterUSB
        self.values = [0, 0, 0, 0, 0] # instr note, channel output, opcode, opdata and duration with unit for each channel
        self.values[0] = self.note.get()
        self.values[1] = 0
        for i in range(channel_num):
            self.values[1] += self.cbvarlist[i].get() * (2**i)
        self.values[2] = self.opc.current()
        self.values[3] = int(self.opd.get())
        self.values[4] = float(self.du.get()) * (1000**(2-self.un.current()))
        # print(self.values[4])


class Scanner(tk.LabelFrame):
    def __init__(self, MainWindow):
        super().__init__(MainWindow.frame)
        self.configure(relief='groove', text='Linear Scanner', font='Helvetica 10 bold')
        self.main = MainWindow
        self.num_scan_instr = 2
        self.scan_instr_list = []

        self.place_progress_bar()
        self.place_guides()
        self.place_add_del()
        self.place_scan_button()
        self.place_sample_num()
        self.place_repetition()
        self.place_DAQ_ch()
        self.place_file_name()
        self.place_scan_instr()


    class scan_instr(tk.LabelFrame):
        def __init__(self, master):
            super().__init__(master)
            self.configure(relief='groove')

            local_label_frame = tk.LabelFrame(self, relief='flat')
            local_label_frame.grid(row=0, column=0, columnspan=2)
            instr_label = tk.Label(local_label_frame, text=r'Instruction #:')
            instr_label.grid(row=0, column=0)
            self.instr_entry = tk.Entry(local_label_frame, width=5)
            self.instr_entry.insert(0, '0')
            self.instr_entry.grid(row=0, column=1)

            start_label = tk.Label(self, text='Start:')
            start_label.grid(row=1, column=0)
            start_label_frame = tk.LabelFrame(self, width=9, relief='flat')
            start_label_frame.grid(row=1, column=1, padx=0, sticky='w')
            self.start_du = tk.Entry(start_label_frame, width=6)
            self.start_du.insert(0, "1")
            self.start_du.grid(row=0, column=0, padx=0)
            self.start_un = newCombobox(start_label_frame, values=duration_unit, width=3, state="readonly")
            self.start_un.grid(row=0, column=1, padx=0)
            self.start_un.current(0)

            end_label = tk.Label(self, text='End:')
            end_label.grid(row=2, column=0)
            end_label_frame = tk.LabelFrame(self, width=9, relief='flat')
            end_label_frame.grid(row=2, column=1, padx=0, sticky='w')
            self.end_du = tk.Entry(end_label_frame, width=6)
            self.end_du.insert(0, "10")
            self.end_du.grid(row=0, column=0, padx=0)
            self.end_un = newCombobox(end_label_frame, values=duration_unit, width=3, state="readonly")
            self.end_un.grid(row=0, column=1, padx=0)
            self.end_un.current(0)

        def compile(self):
            self.start = float(self.start_du.get()) * (1000**(2-self.start_un.current()))
            self.end = float(self.end_du.get()) * (1000**(2-self.end_un.current()))
            self.instr = int(self.instr_entry.get())

    def place_progress_bar(self):
        self.progbar = ttk.Progressbar(self, orient='horizontal', length=200, mode='determinate')
        self.progbar.grid(row=0, column=0)

    def place_guides(self):
        protocol = "Control Protocol:\n\n"
        protocol += "0. A WAIT ... BRANCH structure is needed\n"
        protocol += "1. Turn off Spincore trigger\n"
        protocol += '2. Click "Scan" button\n'
        protocol += "3. Turn on Spincore trigger"
        guides_label = tk.Label(self, text=protocol, bg='sky blue', justify='left')
        guides_label.grid(row=1, column=0, rowspan=3, sticky='ns')

    def place_add_del(self):
        add_del_label = tk.Label(self, text='Add/Delete an instr:')
        add_del_label.grid(row=0, column=1, pady=0)
        self.del_button = tk.Button(self, text="-", width=6, bg=button_color, command=self.del_scan_instr)
        self.del_button.grid(row=0, column=2, sticky='e')
        self.add_button = tk.Button(self, text="+", width=6, bg=button_color, command=self.add_scan_instr)
        self.add_button.grid(row=0, column=3)

    def place_sample_num(self):
        sample_label = tk.Label(self, text='Sample number:')
        sample_label.grid(row=1, column=1, pady=3, sticky='e')
        self.sample_num = tk.Entry(self, width=8)
        self.sample_num.insert(0, "10")
        self.sample_num.grid(row=1, column=2, padx=0, sticky='w')

    def place_repetition(self):
        rep_label = tk.Label(self, text='Repetition:', anchor='e', width=12)
        rep_label.grid(row=1, column=3, padx=0, sticky='e')
        self.repetition = tk.Entry(self, width=8)
        self.repetition.insert(0, "20")
        self.repetition.grid(row=1, column=4, sticky='w')

    def place_DAQ_ch(self):
        daq_label = tk.Label(self, text='DAQ DIO channel:', width=17, anchor='e')
        daq_label.grid(row=1, column=5, sticky='e')
        self.daq_ch = tk.Entry(self, width=18)
        self.daq_ch.insert(0, "Dev3/port0/line0")
        self.daq_ch.grid(row=1, column=6, sticky='w')

    def place_scan_button(self):
        self.scan_button = tk.Button(self, text="Scan", width=6, bg=button_color, command=self.scan)
        self.scan_button.grid(row=0, column=5)
        self.stop_button = tk.Button(self, text="Stop scan", width=9, bg=button_color, command=self.stop_scan)
        self.stop_button.grid(row=0, column=6)
        self.stop_button.configure(state='disabled')

    def place_file_name(self):
        file_name_label = tk.Label(self, text='Save sequence as:')
        file_name_label.grid(row=2, column=1, sticky='e')
        self.file_name = tk.Entry(self, width=24)
        self.file_name.insert(0, "Scan_sequence")
        self.file_name.grid(row=2, column=2, columnspan=3, sticky='w')

        self.datetime_var = tk.IntVar()
        self.datetime_var.set(1)
        self.datetime_cb = tk.Checkbutton(self, variable=self.datetime_var, text=r"Auto append data & time")
        self.datetime_cb.grid(row=2, column=5, columnspan=2)

    def place_scan_instr(self):
        self.instr_frame = tk.LabelFrame(self, relief='flat')
        self.instr_frame.grid(row=3, column=1, columnspan=100, sticky='nw')
        for i in range(self.num_scan_instr):
            self.scan_instr_list.append(self.scan_instr(self.instr_frame))
            self.scan_instr_list[i].grid(row=0, column=i)

    def del_scan_instr(self):
        self.scan_instr_list[-1].destroy()
        del self.scan_instr_list[-1]
        self.num_scan_instr -= 1
        if self.num_scan_instr == 1:
            self.del_button["state"] = "disabled"

    def add_scan_instr(self):
        self.scan_instr_list.append(self.scan_instr(self.instr_frame))
        self.scan_instr_list[self.num_scan_instr].grid(row=0, column=self.num_scan_instr)
        self.num_scan_instr +=1
        if (self.del_button["state"] == "disabled") and (self.num_scan_instr > 1):
            self.del_button["state"] = "normal"

    def scan(self):
        self.widgets_state_change("disabled")
        self.stop_button["state"] = "normal"

        # generate randomized scan parameters
        samp_num = int(self.sample_num.get())
        rep = int(self.repetition.get())
        self.scan_instr_list[0].compile()
        self.scan_param = np.linspace(self.scan_instr_list[0].start, self.scan_instr_list[0].end, samp_num)
        if self.num_scan_instr > 1:
            for i in range(self.num_scan_instr-1):
                self.scan_instr_list[i+1].compile()
                s = np.linspace(self.scan_instr_list[i+1].start, self.scan_instr_list[i+1].end, samp_num)
                self.scan_param = np.vstack((self.scan_param, s))

        # instruction number sanity check
        for i in range(self.num_scan_instr):
            if self.scan_instr_list[i].instr > self.main.num_instr-1:
                tk.messagebox.showerror("Error", "(Scanner) Insturction number doesn't exist.")
                self.widgets_state_change("normal")
                self.stop_button["state"] = "disabled"
                return

        self.scan_param = self.scan_param.T
        self.scan_param = np.repeat(self.scan_param, rep, axis=0)
        np.random.shuffle(self.scan_param)
        # if scan_param is a 1-dim array, it will be turned into 2-dim
        # if scan_param is a 2-dim array, it won't change
        self.scan_param = np.reshape(self.scan_param, (len(self.scan_param), -1))

        # save randomized scan sequence self.scan_param to a local file
        saved = self.save_sequence()
        if not saved:
            self.widgets_state_change("normal")
            self.stop_button["state"] = "disabled"
            return

        # stop and reset spincore
        pb_stop()
        pb_reset()

        # set up a counter for number of points that have been scanned
        self.counter = 0

        # load spincore the first scan parameters
        self.load_param()

        # start spincore and make it ready to be triggered
        pb_start()

        # a DAQ is used to read Spincore "running" signal, a falling edge will be used to trigger loading
        self.task = nidaqmx.Task()
        ch = self.daq_ch.get()
        self.task.di_channels.add_di_chan(ch)
        self.task.timing.cfg_change_detection_timing(rising_edge_chan=ch,
                                                    sample_mode=const.AcquisitionType.CONTINUOUS
                                                    )
        # see https://nidaqmx-python.readthedocs.io/en/latest/task.html for the prototype of callback method
        self.task.register_signal_event(const.Signal.CHANGE_DETECTION_EVENT, self.load_param)

        self.task.start()

    def load_param(self, task_handle=None, signal_type=None, callback_date=None):
        time.sleep(0.02)
        if self.counter < len(self.scan_param):
            for i in range(self.num_scan_instr):
                instr = self.scan_instr_list[i].instr
                # every element in scan_instr_list is supposed to be compiled before
                unit = self.scan_instr_list[i].start_un.current()
                self.main.instrlist[instr].un.current(unit)
                self.main.instrlist[instr].du.delete(0, 'end')
                self.main.instrlist[instr].du.insert(0, str(self.scan_param[self.counter][i]/(1000.0**(2-unit))))

            self.main.loadboard()
            self.progbar['value'] = (self.counter)/len(self.scan_param)*100.0
            self.counter += 1

        elif self.counter == len(self.scan_param):
            self.stop_scan()

        # return an int is necessary for DAQ callback function
        return 0

    def widgets_state_change(self, arg):
        self.del_button["state"] = arg
        self.add_button["state"] = arg
        self.sample_num["state"] = arg
        self.repetition["state"] = arg
        self.daq_ch["state"] = arg
        self.scan_button["state"] = arg
        self.file_name["state"] = arg
        self.datetime_cb["state"] = arg
        for i in range(self.num_scan_instr):
            self.scan_instr_list[i].instr_entry["state"] = arg
            self.scan_instr_list[i].start_du["state"] = arg
            self.scan_instr_list[i].start_un["state"] = arg
            self.scan_instr_list[i].end_du["state"] = arg
            self.scan_instr_list[i].end_un["state"] = arg

    def stop_scan(self):
        try:
            self.task.close()
        except Exception as err:
            logging.warning(err)

        self.widgets_state_change("normal")
        self.stop_button["state"] = "disabled"
        self.progbar['value'] = 0

    def save_sequence(self):
        file_name = ""
        if self.file_name.get():
            file_name += self.file_name.get()
        if self.datetime_var.get():
            if file_name != "":
                file_name += "_"
            file_name += time.strftime("%Y%m%d_%H%M%S")
        file_name += ".ini"
        file_name = r"scan_sequence"+"\\"+file_name
        if os.path.exists(file_name):
            overwrite = tk.messagebox.askyesno("Warning", "File name exits. Continue to overwrite it?", default='no')
            if not overwrite:
                return False

        config = configparser.ConfigParser()
        config.optionxform = str

        config["Settings"] = {}
        samp_num = int(self.sample_num.get())
        rep = int(self.repetition.get())
        config["Settings"]["sample number"] = str(samp_num)
        config["Settings"]["repetition"] = str(rep)
        config["Settings"]["element number"] = str(samp_num*rep)
        config["Settings"]["scan device"] = "SpinCore"
        instr_init = self.scan_instr_list[0].instr
        config["Settings"]["scan param"] = f"instr no. {instr_init}"
        for i in range(len(self.scan_param)):
            config[f"Sequence element {i}"] = {}
            for j in range(self.num_scan_instr):
                instr = self.scan_instr_list[j].instr
                config[f"Sequence element {i}"][f"SpinCore [instr no. {instr}]"] = str(self.scan_param[i][j])
        configfile = open(file_name, "w")
        config.write(configfile)
        configfile.close()

        # save scan sequence to camera folder, so the camera program can read it
        configfile = open(r"C:\Users\dur!p5\github\pixelfly-python-control\scan_sequence\latest_sequence.ini", "w")
        config.write(configfile)
        configfile.close()

        return True

    def chop_scan_instr(self, new_num):
        while self.num_scan_instr > new_num:
            self.del_scan_instr()
        while self.num_scan_instr < new_num:
            self.add_scan_instr()


class MainWindow(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master.title("SpinCore PulseBlasterUSB")
        self.master.geometry('1200x800')
        self.num_instr = 6 # number of instructions (one instruction is one column in this GUI)
        self.instrlist = [] # used to save all the instructions
        self.pack()
        self.place_scrollbar()
        self.place_control_widgets()
        self.place_scanner()
        self.place_main_cols()
        self.init_spincore()

    def place_scrollbar(self):
        # Create scrollbars
        # Followed the following threads to add scroll bars:
        # https://stackoverflow.com/questions/3085696/adding-a-scrollbar-to-a-group-of-widgets-in-tkinter
        # https://stackoverflow.com/questions/17355902/tkinter-binding-mousewheel-to-scrollbar
        self.canvas = tk.Canvas(self.master, borderwidth=0, highlightthickness=0)
        self.frame = tk.Frame(self.canvas)
        self.frame.configure(relief='flat', borderwidth=0, highlightthickness=0)
        vsb = tk.Scrollbar(self.master, orient="vertical", command=self.canvas.yview)
        hsb = tk.Scrollbar(self.master, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.configure(xscrollcommand=hsb.set)

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.create_window((4,4), window=self.frame, anchor="nw")

        self.frame.bind("<Configure>", lambda event: self.onFrameConfigure())
        self.canvas.bind_all("<MouseWheel>", lambda event: self.on_mousewheel(event))

    def place_control_widgets(self):
        self.control_frame = tk.LabelFrame(self.frame, relief='groove', text='General Control', font='Helvetica 10 bold')
        self.control_frame.grid(row=0, column=0, ipadx=5, ipady=2, columnspan=1)
        # Create top control widgets
        add_del_label = tk.Label(self.control_frame, text=r"Add/Delete an instruction: ")
        add_del_label.grid(row=0, column=0, columnspan=2, sticky='e')

        # delete the last instruction column
        self.del_button = tk.Button(self.control_frame, text="-", width=6, bg=button_color, command=self.del_instr)
        self.del_button.grid(row=0, column=2)

        # add an instruction olumn after the last one
        add_button = tk.Button(self.control_frame, text="+", width=6, bg=button_color, command=self.add_instr)
        add_button.grid(row=0, column=3, sticky='w')

        # load instructions into PulseBlasterUSB
        loadboard_button = tk.Button(self.control_frame, text="Load board", width=10, bg=button_color, command=self.loadboard)
        loadboard_button.grid(row=0, column=5, sticky='e')

        # software trigger PulseBlasterUSB
        softtrig_button = tk.Button(self.control_frame, text="Software trig", width=10, bg=button_color, command=self.software_trig)
        softtrig_button.grid(row=0, column=6)

        # toggle scanner widgets
        softtrig_button = tk.Button(self.control_frame, text="Toggle scanner", width=13, bg=button_color, command=self.toggle_scanner)
        softtrig_button.grid(row=0, column=7)

        # file location label
        location_label = tk.Label(self.control_frame, text="File name to load: ")
        location_label.grid(row=2, rowspan=2, column=0, columnspan=2, sticky='e')

        # location of .txt to load
        self.location_text = tk.Text(self.control_frame, height=3, width=65)
        self.location_text.grid(row=2, rowspan =2, column=2, columnspan=5)

        # browse and choose a .txt file
        browsefile_button = tk.Button(self.control_frame, text="Browse files", width=10, bg=button_color, command=self.browse_file)
        browsefile_button.grid(row=2, column=7, padx=5, pady=5, sticky='e')

        # load configuraion from a .txt file to this GUI
        loadconfig_button = tk.Button(self.control_frame, text="Load configs", width=10, bg=button_color, command=self.load_config)
        loadconfig_button.grid(row=3, column=7, padx=5, pady=5, sticky='e')

        # saved file name label
        filename_label = tk.Label(self.control_frame, text="File name to save: ")
        filename_label.grid(row=4, column=0, columnspan=2, sticky='e')

        # name to append to file name when saving
        self.filename_entry = tk.Entry(self.control_frame, width=32)
        self.filename_entry.insert(0, "PulseBlasterUSB_configs")
        self.filename_entry.grid(row=4, column=2, columnspan=2, sticky='w')

        # whether to append date/time to saved file name
        self.datetime_var = tk.IntVar()
        self.datetime_var.set(1)
        self.datetime_cb = tk.Checkbutton(self.control_frame, variable=self.datetime_var, text=r"Auto append data & time")
        self.datetime_cb.grid(row=4, column=4, columnspan=3, sticky='w')

        # save configuraion to a .txt file
        save_button = tk.Button(self.control_frame, text="Save configs", width=10, bg=button_color, command=self.save_config)
        save_button.grid(row=4, column=7, padx=5, pady=2, sticky='e')

        for i in range(4):
            bottom_empty_label = tk.Label(self.frame, text="")
            bottom_empty_label.grid(row=100+i, column=0)

    def place_scanner(self):
        self.scanner = Scanner(self)
        self.scanner.grid(row=1, column=0, ipadx=5, ipady=2, columnspan=100, sticky='nw')
        # self.scanner.grid_remove()

    def place_main_cols(self):
        # create main columns in this GUI
        self.instr_frame = tk.LabelFrame(self.frame, relief='flat')
        self.instr_frame.grid(row=2, column=0, columnspan=100, sticky='nw')
        # add a sub frame here so when instruction columns are added/deleted,
        # main frame column size doesn't change

        # Create the first column: decriptive labels
        self.descr_col = Descr(self.instr_frame)
        self.descr_col.grid(row=0, column=0)

        # Create 2nd to nth columns: Spincore instruction data
        for i in range(self.num_instr):
            self.instrlist.append(Instr(self.instr_frame, i))
            self.instrlist[i].grid(row=0, column=i+1)

    # initiate Spincore PulseBlaster USB
    def init_spincore(self):
        # downloaded form http://www.spincore.com/support/SpinAPI_Python_Wrapper/Python_Wrapper_Main.shtml
        # And modified by Qian W., July 24, 2020
        # Enable the SpinCore log file
        pb_set_debug(1)

        print("Using SpinAPI Library version %s" % pb_get_version())
        print("Found %d board(s) in the system.\n" % pb_count_boards())
        print("This program maniputales the TTL outputs of the PulseBlasterUSB.\n\n")

        pb_select_board(0)

        # pb_init() function has to be called before any programming/start/stop instructions
        if pb_init() != 0:
        	print("Error initializing board: %s" % pb_get_error())
        	input("Please press a key to continue.")
        	exit(-1)

        # Configure the core clock, in MHz
        pb_core_clock(100.0)

    # scrollbar funtion
    def onFrameConfigure(self):
        '''Reset the scroll region to encompass the inner frame'''
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    # scrollbar function
    def on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    # delete the last instruction column
    def del_instr(self):
        self.instrlist[-1].destroy()
        del self.instrlist[-1]
        self.num_instr -= 1
        if self.num_instr == 1:
            self.del_button["state"] = "disabled"

    # add an instruction column after the last one
    def add_instr(self):
        self.instrlist.append(Instr(self.instr_frame, self.num_instr))
        self.num_instr += 1
        self.instrlist[-1].grid(row=0, column=self.num_instr)
        # both 'num_instr' and 'instrlist' are lists, in this way, the list can be manipulated
        if (self.del_button["state"] == "disabled") and (self.num_instr > 1):
            self.del_button["state"] = "normal"

    # load instrctions into PulseBlasterUSB
    def loadboard(self):
        pb_start_programming(PULSE_PROGRAM)
        for i in range(self.num_instr):
            self.instrlist[i].compile_instr()
            pb_inst_pbonly(*self.instrlist[i].values[1:5])
        pb_stop_programming()

    # software trigger PulseBlasterUSB
    def software_trig(self):
        pb_start()

    # toggle scanner widgets
    def toggle_scanner(self):
        if self.scanner.winfo_viewable():
            self.scanner.grid_remove()
        else:
            self.scanner.grid()

    # browse and choose a .txt file
    def browse_file(self):
        file_loca = filedialog.askopenfilename(initialdir="saved_configs", title="Select a file",
                                                filetypes=(("config files", "*.ini"), ("all files", "*.*")))
        if len(file_loca) > 0:
            self.location_text.delete(1.0, 'end')
            self.location_text.insert(1.0, file_loca)

    # this function is used when a saved configuration is loaded to GUI, it's used to make the number of instruction correct
    def chop_instr(self, new_num_instr):
        while new_num_instr < self.num_instr:
            self.del_instr()
        while new_num_instr > self.num_instr:
            self.add_instr()

    def load_config(self):
        file_loca = self.location_text.get(1.0, 'end')[:-1]
        if not os.path.exists(file_loca):
            tk.messagebox.showerror("Error", "File doesn't exist.")
            return

        config = configparser.ConfigParser()
        config.read(file_loca) # remove '\n' at the end of location_text.get()

        dev_name = [dev.strip() for dev in config["General settings"].get("devices").split(',')]
        for i in range(channel_num):
            self.descr_col.ch_label_list[i].delete(0, 'end')
            self.descr_col.ch_label_list[i].insert(0, dev_name[channel_num-1-i])
        new_num_instr = int(config["General settings"].get("number of instructions"))
        self.chop_instr(new_num_instr)

        for i in range(self.num_instr):
            self.instrlist[i].note.delete(0, 'end')
            self.instrlist[i].note.insert(0, config[f"Instr {i}"].get("instr note"))
            self.instrlist[i].du.delete(0, 'end')
            self.instrlist[i].du.insert(0, config[f"Instr {i}"].get("duration time"))
            self.instrlist[i].un.current(duration_unit.index(config[f"Instr {i}"].get("duration unit")))
            self.instrlist[i].opd.delete(0, 'end')
            self.instrlist[i].opd.insert(0, config[f"Instr {i}"].get("op data"))
            self.instrlist[i].opc.current(opcodes.index(config[f"Instr {i}"].get("op code")))
            for j in range(channel_num):
                self.instrlist[i].cbvarlist[j].set(int(config[f"Instr {i}"]["ttl output pattern"][channel_num+1-j]))

        self.scanner.sample_num.delete(0, 'end')
        self.scanner.sample_num.insert(0, config["Scanner settings"].get("sample number"))
        self.scanner.repetition.delete(0, 'end')
        self.scanner.repetition.insert(0, config["Scanner settings"].get("repetition"))
        new_num_scan_instr = int(config["Scanner settings"].get("number of scanned instr"))
        self.scanner.chop_scan_instr(new_num_scan_instr)

        for i in range(self.scanner.num_scan_instr):
            scan_instr = self.scanner.scan_instr_list[i]
            scan_instr.instr_entry.delete(0, 'end')
            scan_instr.instr_entry.insert(0, config[f"Scanned Instr {i}"].get("instr no."))
            scan_instr.start_du.delete(0, 'end')
            scan_instr.start_du.insert(0, config[f"Scanned Instr {i}"].get("start duration"))
            scan_instr.start_un.current(duration_unit.index(config[f"Scanned Instr {i}"].get("start unit")))
            scan_instr.end_du.delete(0, 'end')
            scan_instr.end_du.insert(0, config[f"Scanned Instr {i}"].get("end duration"))
            scan_instr.end_un.current(duration_unit.index(config[f"Scanned Instr {i}"].get("end unit")))


    def save_config(self):
        file_name = ""
        if self.filename_entry.get():
            file_name += self.filename_entry.get()
        if self.datetime_var.get():
            if file_name != "":
                file_name += "_"
            file_name += time.strftime("%Y%m%d_%H%M%S")
        file_name += ".ini"
        file_name = r"saved_configs"+"\\"+file_name
        if os.path.exists(file_name):
            overwrite = tk.messagebox.askyesno("Warning", "File name exits. Continue to overwrite it?", default='no')
            if not overwrite:
                return

        config = configparser.ConfigParser(allow_no_value=True)

        self.descr_col.compile_ch_label_text()
        config["General settings"] = {}
        config["General settings"]["number of instructions"] = str(self.num_instr)
        config["General settings"]["# form channel {:d} to channel 0".format(channel_num-1)] = None
        config["General settings"]["devices"] = ", ".join(self.descr_col.ch_label_text)
        for i in range(self.num_instr):
            self.instrlist[i].compile_instr()
            config[f"Instr {i}"] = {}
            config[f"Instr {i}"]["instr note"] = self.instrlist[i].values[0]
            config[f"Instr {i}"]["ttl output pattern"] = '0b' + str(bin(self.instrlist[i].values[1]))[2:].zfill(channel_num)
            config[f"Instr {i}"]["op code"] = opcodes[self.instrlist[i].values[2]]
            config[f"Instr {i}"]["op data"] = str(self.instrlist[i].values[3])
            config[f"Instr {i}"]["duration time"] = self.instrlist[i].du.get()
            config[f"Instr {i}"]["duration unit"] = duration_unit[self.instrlist[i].un.current()]

        config["Scanner settings"] = {}
        config["Scanner settings"]["sample number"] = self.scanner.sample_num.get()
        config["Scanner settings"]["repetition"] = self.scanner.repetition.get()
        config["Scanner settings"]["number of scanned instr"] = str(self.scanner.num_scan_instr)
        for i in range(self.scanner.num_scan_instr):
            config[f"Scanned Instr {i}"] = {}
            config[f"Scanned Instr {i}"]["instr no."] = self.scanner.scan_instr_list[i].instr_entry.get()
            config[f"Scanned Instr {i}"]["start duration"] = self.scanner.scan_instr_list[i].start_du.get()
            config[f"Scanned Instr {i}"]["start unit"] = duration_unit[self.scanner.scan_instr_list[i].start_un.current()]
            config[f"Scanned Instr {i}"]["end duration"] = self.scanner.scan_instr_list[i].end_du.get()
            config[f"Scanned Instr {i}"]["end unit"] = duration_unit[self.scanner.scan_instr_list[i].end_un.current()]

        configfile = open(file_name, "w")
        config.write(configfile)
        configfile.close()



root = tk.Tk()
mygui = MainWindow(root)
mygui.mainloop()

# pb_close function has to be called at the end of any programming/start/stop instructions
pb_close()
