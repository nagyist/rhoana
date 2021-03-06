#-------------------------
#3d Renderer
#Daniel Miron
#7/5/2013
#
#Allows 3d viewing of nerve cord or neuron stacks.
#Includes ability to fully rotate image in 3 dimensions and to mark locations in 3-space
#-------------------------

import h5py
import numpy as np
import glob
import os
import sys
sys.path.append(r'c:\Python27\Lib\site-packages')
import pickle
import math
import time
from OpenGL.GLUT import *
from OpenGL.GLU import *
from OpenGL.GL import *
import arcball as arc

from pysqlite2 import dbapi2 as sqlite

import cv2

class Viewer:
    def __init__(self, directory, label_ids, resolution_level, location):
        self.st = time.time()
        self.arcball = None
        self.directory = directory
        self.w = resolution_level
        self.w_str = "w={0:08}".format(resolution_level)
        self.label_folder = self.directory +"\\ids\\tiles\\" + self.w_str
        
        self.segment_file = self.directory + "\\ids\\segmentInfo.db"
        self.z_folders = glob.glob(self.label_folder + "\\*")
        h5_file = h5py.File(glob.glob(self.z_folders[0] + "\\*")[0], "r")
        self.label_key = h5_file.keys()[0]
        self.shape = np.shape(h5_file[self.label_key][...])
        
        self.tile_rows = self.shape[0]
        self.tile_columns = self.shape[1]
        
        self.tiles_per_layer = len(glob.glob(self.z_folders[0] + "\\*"))
        
        #taking sqrt assumes same number of tiles in x direction as y direction
        self.rows = self.shape[0]*math.sqrt(self.tiles_per_layer)
        self.columns = self.shape[1]*math.sqrt(self.tiles_per_layer)
        self.layers = len(self.z_folders)
        
        #need to figure out way to get num_tiles in each direction when not square
        '''self.rows = self.shape[0]*num_tiles_x
        self.columns =self.shape[1]*num_tiles_y'''
        
        self.label_ids = label_ids
        self.contours = self.find_contours(label_ids, range(self.layers))
        self.win_h = 0
        self.win_w = 0
        
        self.left = None
        self.slice = None
        self.pick_location = location
        self.main()
        
    def main(self):
        #self.contours = self.load_contours(contour_file)
        #set window height and width
        self.win_h = 1000
        self.win_w = 1000
        self.arcball = self.create_arcball()
        glutInit(sys.argv)
        glutInitDisplayMode(GLUT_RGBA | GLUT_DOUBLE | GLUT_DEPTH)
        glutInitWindowSize(self.win_w, self.win_h) #width, height
        glutCreateWindow("Nerve Cord")
        
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(65, 1, 1, 10)
        glMatrixMode(GL_MODELVIEW)
        
        self.back_tesselator = gluNewTess()
        gluTessCallback(self.back_tesselator, GLU_TESS_BEGIN, glBegin)
        gluTessCallback(self.back_tesselator, GLU_TESS_END, glEnd)
        gluTessCallback(self.back_tesselator, GLU_TESS_VERTEX, self.back_vertex)
        
        self.front_tesselator = gluNewTess()
        gluTessCallback(self.front_tesselator, GLU_TESS_BEGIN, glBegin)
        gluTessCallback(self.front_tesselator, GLU_TESS_END, glEnd)
        gluTessCallback(self.front_tesselator, GLU_TESS_VERTEX, self.front_vertex) 
        
        glEnable(GL_DEPTH_TEST)
        
        self.make_display_lists()
        glutDisplayFunc(self.draw)
        glutKeyboardFunc(self.keyboard)
        glutMouseFunc(self.on_click)
        glutMotionFunc(self.on_drag)
        
        #window for viewing z slices
        glutCreateWindow("single layer")
        glutDisplayFunc(self.draw_slice)
        
        
        glutMainLoop()
        return
    
    def find_contours(self, label_ids, z_list):
        tot_contours = []
        for label in label_ids:
            tile_list = self.get_tile_list(label, z_list)
            for tile in tile_list:
                x = tile[1]
                y = tile[2]
                z = tile[3]
                if True:
                    z_folder = self.z_folders[z]
                    tile_files = glob.glob(z_folder + "\\*")
                    for tile_name in tile_files:
                        if os.path.basename(tile_name) == "y={0:08},x={1:08}.hdf5".format(y, x):
                            t_file = h5py.File(tile_name, "r")
                            labels = t_file[self.label_key][...]
                            labels[labels!=label] = 0
                            labels[labels==label] = 255
                            labels = labels.astype(np.uint8)
                            t_file.close()
                            buffer_array = np.zeros((np.shape(labels)[0]+2, np.shape(labels)[1]+2), np.uint8) #buffer by one pixel on each side
                            buffer_array[1:-1, 1:-1] = labels
                            contours, hierarchy  = cv2.findContours(buffer_array, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                            if not contours == []:
                                contours = [np.array(cnt) for cnt in contours]
                                for idx, cnt in enumerate(contours):
                                    new_cnt = np.zeros((cnt.shape[0], 3))
                                    new_cnt[:, 0] = cnt[:, 0, 0] - 1 + x * self.tile_columns
                                    new_cnt[:, 1] = cnt[:, 0, 1] - 1 + y*self.tile_rows
                                    new_cnt[:, 2] = z
                                    contours[idx] = new_cnt
                                tot_contours+=contours
                        
        return tot_contours                        
                
            
            
    def get_tile_list(self, label, z_list):
        con = sqlite.connect(self.segment_file)
        cur = con.cursor()
        #w = 0 requirement specifies highest resolution
        cur.execute('select w,x,y,z from idTileIndex where w =' +str(self.w) + ' AND id =' + str(label))
        tile_list = cur.fetchall()
        end_tile_list = []
        for tile in tile_list:
            if tile[3] in z_list:
                end_tile_list += [tile]
        return end_tile_list
    
    def organize_chunks(self, keys):
        chunk_list = []
        for key in keys:
            chunk_list += self.chunk_map[key]
        chunk_list.sort(key=lambda x: x[2]) #sort w/respect to z
        chunk_list.reverse() #make back to front
        return chunk_list
        
    def create_arcball(self):
        arcball = arc.Arcball()
        #locate the arcball center at center of window with radius half the width
        arcball.place([self.win_w/2, self.win_h/2], self.win_w/2)
        return arcball
        
    def make_display_lists(self):
        self.display_lists = glGenLists(2) #first list for front, second for back
        self.make_front_list()
        self.make_back_list()
        
    def make_back_list(self):
        '''Creates a display list to encode color for image. Not seen by user'''
        glNewList(self.display_lists +1, GL_COMPILE)
        
        glDrawBuffer(GL_BACK)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glTranslatef(-.9, .9, .9)
        glScalef(1.8/self.columns, -1.8/self.rows, -1.8/self.layers)
        #draw the layers
        for cnt in self.contours:
            gluTessBeginPolygon(self.back_tesselator, None)
            gluTessBeginContour(self.back_tesselator)
            for vtx in cnt:
                gluTessVertex(self.back_tesselator, vtx, vtx)
            gluTessEndContour(self.back_tesselator)
            gluTessEndPolygon(self.back_tesselator)
        
        glColor3f(.5, .5, .5)
        glBegin(GL_POLYGON)
        glVertex3f(*self.x_axis[2][0])
        glVertex3f(*self.x_axis[2][1])
        glVertex3f(*self.x_axis[3][1])
        glVertex3f(*self.x_axis[3][0])
        glEnd()
        
        glPopMatrix()
        
        glEndList()
        
    def make_front_list(self):
        '''Creates a display list to draw a box and the data scaled to .9*the size of the window.
        This list deals with the display seen by the user'''
        
        glNewList(self.display_lists, GL_COMPILE)
        
        glDrawBuffer(GL_FRONT)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glTranslatef(-.9, .9, .9)
        glScalef(1.8/self.columns, -1.8/self.rows, -1.8/self.layers)
        
        #draw the layers
        glColor3f(1.0, 1.0, 0.0)
        for cnt in self.contours:
            gluTessBeginPolygon(self.front_tesselator, None)
            gluTessBeginContour(self.front_tesselator)
            for vtx in cnt:
                gluTessVertex(self.front_tesselator, vtx, vtx)
            gluTessEndContour(self.front_tesselator)
            gluTessEndPolygon(self.front_tesselator)
            
        #make a box around the image
        self.axes()
        glBegin(GL_LINES)
        glColor3f(1.0, 0, 0) #x in red
        for line in self.x_axis:
            glVertex3f(line[0][0], line[0][1], line[0][2])
            glVertex3f(line[1][0], line[1][1], line[1][2])
        glColor3f(0,1.0, 0) #y in green
        for line in self.y_axis:
            glVertex3f(line[0][0], line[0][1], line[0][2])
            glVertex3f(line[1][0], line[1][1], line[1][2])
        glColor3f(0,0,1.0) #z in blue
        for line in self.z_axis:
            glVertex3f(line[0][0], line[0][1], line[0][2])
            glVertex3f(line[1][0], line[1][1], line[1][2])
        glEnd()  
        
        #make a back panel for easy orientation
        glColor3f(.5, .5, .5)
        glBegin(GL_POLYGON)
        glVertex3f(*self.x_axis[2][0])
        glVertex3f(*self.x_axis[2][1])
        glVertex3f(*self.x_axis[3][1])
        glVertex3f(*self.x_axis[3][0])
        glEnd()
        
        glPopMatrix()
        
        glEndList()
        
    def front_vertex(self, vertex):
        glVertex3f(*vertex)
        
    def back_vertex(self, vertex):
        '''sets the color of a single vertex and draws it'''
        #scale by dim-1 to include black 
        #multiply by -1 and add 1 to invert color axis
        glColor3f(1.0*vertex[0]/(self.columns-1), -1.0*vertex[1]/(self.rows-1)+1.0, -1.0*vertex[2]/(self.layers-1)+1.0)
        glVertex3f(*vertex)
        
    def draw(self):
        '''draws an image'''
        glLoadIdentity()
        gluLookAt(0, 0, 3, 0, 0, 2, 0,1,0)
        glMultMatrixd(self.arcball.matrix().T)
        
        glCallList(self.display_lists)
        glCallList(self.display_lists+1)
        self.draw_marker()
        
        glFlush()
        
        return
        
    def draw_marker(self):
        '''Draws a sphere around the chosen point. Color is inverse of chosen pixel'''
        glDrawBuffer(GL_FRONT)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        location = self.pick_location
        glTranslatef(float(1.8*location[0])/self.columns-.9,
                    -(float(1.8*location[1])/self.rows-.9),
                    -(float(1.8*location[2])/self.layers-.9))
        glScalef(1.8/self.layers, 1.8/self.layers, 1.8/self.layers)
        location = self.pick_location
        
        #Figure out how to deal with color of neurons versus color of marker
        glColor3f(1-(1.0*location[0]/(self.columns-1)),
            1-(-1.0*location[1]/(self.rows-1)+1.0), 
            1-(-1.0*location[2]/(self.layers-1)+1.0))
        glutSolidSphere(5, 50, 50)
        
        glPopMatrix()
        
    def keyboard(self, key, x, y):
        return
        
    def on_click(self, button, state, x, y):
        #Left click for arcball rotation
        if (button == GLUT_LEFT_BUTTON and state == GLUT_DOWN):
            self.left = True #turn on dragging rotation
            self.arcball.down((x,y))
        #right click to select a pixel location
        elif (button == GLUT_RIGHT_BUTTON and state == GLUT_DOWN):
            self.left = False #turn off dragging rotation
            self.pick_location = self.pick(x,y)
            print self.pick_location
            self.has_marker = True
            self.slice = self.show_slice(self.pick_location)
        
    #Fix data gathering for slice to work with mojo format
    def show_slice(self, location):
        '''displays a single selected z slice in 2-d'''
        layer = self.find_contours(self.label_ids, [location[2]])
        return layer
        
    def draw_slice(self):
        '''draws a single z slice'''
        if self.slice == None:
            self.slice = self.show_slice(self.pick_location)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glTranslatef(-.9, .9, .9)
        glScalef(1.8/self.columns, -1.8/self.rows, -1.8/self.layers)
        
        #draw the layers
        for cnt in self.slice:
            gluTessBeginPolygon(self.front_tesselator, None)
            gluTessBeginContour(self.front_tesselator)
            for vtx in cnt:
                gluTessVertex(self.front_tesselator, vtx, vtx)
            gluTessEndContour(self.front_tesselator)
            gluTessEndPolygon(self.front_tesselator)
        
        glPopMatrix()
        
        glutSwapBuffers()
    
    def pick(self, x,y):
        '''gets the (x,y,z) location in the full volume of a chosen pixel'''
        click_color = None
        glReadBuffer(GL_BACK)
        click_color = glReadPixels(x,self.win_h-y, 1,1, GL_RGB, GL_FLOAT)[0][0]
        location  = [int(click_color[0]*(self.columns-1)), 
                    int(-(click_color[1]-1)*(self.rows-1)), int(-(click_color[2]-1)*((self.layers-1)))]
        return location
        
    def on_drag(self, x, y):
        if self.left:
            self.arcball.drag((x,y))
            self.draw()
        
    def read_chunk_map(self, chunk_file):
        return pickle.load(open(chunk_file, "rb"))
        
    def save_contours(self, contour_file):
        pickle.dump(self.contours, open(contour_file, "wb"))
        return
        
    def load_contours(self, contour_file):
        return pickle.load(open(contour_file, "rb"))
        
    def axes(self):
        '''generates vertices for a box'''
        self.x_axis = [[[0,0,0], [self.columns, 0,0]], [[0,self.rows,0], [self.columns, self.rows, 0]],
                        [[0,0,self.layers], [self.columns,0,self.layers]], [[0, self.rows, self.layers], [self.columns, self.rows, self.layers]]]
        self.y_axis = [[[0,0,0], [0, self.rows,0]], [[self.columns,0,0],[self.columns, self.rows, 0]], [[0,0,self.layers], [0,self.rows, self.layers]],
                        [[self.columns, 0, self.layers],[self.columns, self.rows, self.layers]]]
        self.z_axis = [[[0,0,0], [0,0,self.layers]], [[self.columns,0,0],[self.columns, 0, self.layers]],
                        [[0, self.rows,0], [0, self.rows, self.layers]],[[self.columns, self.rows, 0],[self.columns, self.rows, self.layers]]]
          

#viewer = Viewer('C:\\MojoData\\ac3x75\\mojo', [3036],0, (500, 500, 0))
viewer = Viewer('C:\\Users\\DanielMiron\\Documents\\Mojo\\Cube2\\mojo', [2761052],4, (500, 500, 0))
#viewer.main(1000,1000, [6642,4627], r'C:\Users\DanielMiron\Documents\3d_rendering\contours_full.p')
