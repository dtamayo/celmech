import numpy as np
from collections import OrderedDict
from sympy import symbols, S
from celmech.hamiltonian import Hamiltonian
from celmech.disturbing_function import get_fg_coeffs
from celmech.transformations import ActionAngleToXY, XYToActionAngle, poincare_vars_from_sim
import rebound

def rotate_Poincare_Gammas_To_ZW(Gamma1,gamma1,Gamma2,gamma2,f,g,inverse=False):
    if inverse is True:
        g = -g
    X1,Y1 = ActionAngleToXY(Gamma1,gamma1)
    X2,Y2 = ActionAngleToXY(Gamma2,gamma2)
    norm = np.sqrt(f*f + g*g)
    rotation_matrix = np.array([[f,g],[-g,f]]) / norm
    ZX,WX = np.dot(rotation_matrix , np.array([X1,X2]) )
    ZY,WY = np.dot(rotation_matrix , np.array([Y1,Y2]) )
    Z,z = XYToActionAngle(ZX,ZY)
    W,w = XYToActionAngle(WX,WY)
    return Z,z,W,w

def calc_expansion_params(G, masses, j, k, a10):
    p = {'j':j, 'k':k, 'G':G, 'masses':masses, 'a10':a10}       
    p['a20'] = a10*(j/(j-k))**(2./3.)
    p['Lambda10'] = masses[1]*np.sqrt(G*masses[0]*p['a10'])
    p['Lambda20'] = masses[2]*np.sqrt(G*masses[0]*p['a20'])
    p['n10'] = masses[1]**3*(G*masses[0])**2/p['Lambda10']**3
    p['n20'] = masses[2]**3*(G*masses[0])**2/p['Lambda20']**3
    Dn1DL1 = -3. * p['n10']/ p['Lambda10']
    Dn2DL2 = -3. * p['n20'] / p['Lambda20']
    f,g = get_fg_coeffs(j,k)
    p['ff']  = np.sqrt(2)*f/np.sqrt(p['Lambda10'])
    p['gg']  = np.sqrt(2)*g/np.sqrt(p['Lambda20'])
    fac = np.sqrt(2.*k*(p['ff']**2+p['gg']**2))**k
    p['Acoeff'] = Dn1DL1*(j-k)**2 + Dn2DL2*j**2
    p['Ccoeff'] = -G**2*masses[0]*masses[2]**3* masses[1]/p['Lambda20']**2*fac
    p['Phiscale'] = 2.**((k-6.)/(k-4.))*(p['Ccoeff']/p['Acoeff'])**(2./(4.-k))
    p['timescale'] = 8./(p['Phiscale']*p['Acoeff'])
    return p

def get_second_order_phiprime(Phi_eq):
    return (4*Phi_eq**2 - 2.)/3.

class Andoyer(Hamiltonian):
    def __init__(self, j, k, Phi, phi, a10=1., G=1., masses=[1.,1.e-5,1.e-5], W=0., w=0., Brouwer=-1.e-4, K=0., deltalambda=np.pi, lambda1=0.):
        sX, sY, sW, sw, sBrouwer, sK, sdeltalambda, slambda1 = symbols('X, Y, W, w, Brouwer, K, \Delta\lambda, lambda1')
        sPhiprime, sk, sj, sG, smasses, sa10 = symbols('Phiprime, k, j, G, masses, a10')
        X = np.sqrt(2.*Phi)*np.cos(phi)
        Y = np.sqrt(2.*Phi)*np.sin(phi)
        self.y = OrderedDict([
                        (sX, np.sqrt(2.*Phi)*np.cos(phi)), 
                        (sY, np.sqrt(2.*Phi)*np.sin(phi)), 
                        (sW, W), 
                        (sw, w), 
                        (sBrouwer, Brouwer), 
                        (sK, K), 
                        (sdeltalambda, deltalambda), 
                        (slambda1, lambda1)])
        self.params = calc_expansion_params(G, masses, j, k, a10)
        p = self.params
        p['Bcoeff'] = Brouwer*p['Acoeff']
        p['Phiprime'] = -p['Bcoeff'] * p['timescale']/3.
        self.Hparams = {sk:k, sPhiprime:p['Phiprime']}
        self.H = (sX**2 + sY**2)**2 - S(3)/S(2)*sPhiprime*(sX**2 + sY**2) + (sX**2 + sY**2)**((sk-S(1))/S(2))*sX

    @classmethod
    def from_elements(cls, j, k, Phistar, libfac, a10=1., G=1., masses=[1.,1.e-5,1.e-5], W=0., w=0., K=0., deltalambda=np.pi, lambda1=0.):
        p = calc_expansion_params(G, masses, j, k, a10)
        Xstar = -np.sqrt(2*Phistar)
        Phiprime = get_second_order_phiprime(Xstar)
        Bcoeff = -3.*Phiprime/p['timescale']
        Brouwer = Bcoeff/p['Acoeff']
        #Brouwer /= p['Phiscale']
        Phi = Phistar
        phi = np.pi

        return cls(j, k, Phi, phi, a10, G, masses, W, w, Brouwer, K, deltalambda, lambda1)
    @classmethod
    def from_poincare(cls, pvars,G,masses,j,k,a10):
        Lambda1, lambda1, Gamma1, gamma1, Lambda2, lambda2, Gamma2, gamma2 = pvars
        p = calc_expansion_params(G, masses, j, k, a10)
        
        dL1 = Lambda1-p['Lambda10']
        dL2 = Lambda2-p['Lambda20']
        Z,z,W,w = rotate_Poincare_Gammas_To_ZW(Gamma1,gamma1,Gamma2,gamma2,p['ff'],p['gg'])
        K  = ( j * dL1 + (j-k) * dL2 ) / (j-k)
        Pa = -dL1 / (j-k) 
        Brouwer = Pa - Z/k
        phi = j * lambda2 - (j-k) * lambda1 + k * z
        Phi = Z / k 
         
        andvars = cls(j, k, Phi, phi, a10, G, masses, W, w, Brouwer, K, lambda2-lambda1, lambda1)
        andvars.scale_actions(1./p['Phiscale']) 
        return andvars

    @classmethod
    def from_Simulation(cls, sim, j, k, a10=None, i1=1, i2=2, average_synodic_terms=False):
        if a10 is None:
            a10 = sim.particles[i1].a
        poincare_vars = poincare_vars_from_sim(sim, average_synodic_terms)
        ps = sim.particles
        return Andoyer.from_poincare(poincare_vars, sim.G, [ps[0].m, ps[i1].m, ps[i2].m], j, k, a10)

    def to_poincare(self):
        p = self.params
        j = p['j']
        k = p['k']
        self.scale_actions(p['Phiscale'])
        lambda2 = self.lambda1 + self.deltalambda
        Z = k*self.Phi
        theta = j*self.deltalambda + k*self.lambda1 # jlambda2 - (j-k)lambda1
        z = np.mod( (self.phi - theta) / k ,2*np.pi)
        Pa = self.Brouwer + Z/float(k)
        dL1 = -Pa*(j-k)    
        dL2 =((j-k) * self.K - j * dL1)/(j-k) 

        Lambda1 = p['Lambda10']+dL1
        Lambda2 = p['Lambda20']+dL2 

        Gamma1,gamma1,Gamma2,gamma2 = rotate_Poincare_Gammas_To_ZW(Z,z,self.W,self.w,p['ff'],p['gg'], inverse=True)
        self.scale_actions(1./p['Phiscale'])
        return [ Lambda1, self.lambda1, Gamma1, gamma1, Lambda2, lambda2, Gamma2, gamma2 ]

    def to_sim(self):
        pvars = self.to_poincare()
        masses = self.params['masses']
        G = self.params['G']
        
        sim = rebound.Simulation()
        sim.G = G
        sim.add(m=masses[0])
        for i in range(1, len(masses)):
            Lambda, l, Gamma, gamma = pvars[4*(i-1):4*i]
            a = Lambda**2/masses[i]**2/G/masses[0]
            e = np.sqrt(1.-(1.-Gamma/Lambda)**2)
            sim.add(m=masses[i], a=a, e=e, pomega=-gamma, l=l)
        sim.move_to_com()
        return sim
         
    def scale_actions(self, scale):
        self.y[symbols('W')] *= scale
        self.y[symbols('Brouwer')] *= scale
        self.y[symbols('K')] *= scale
        self.y[symbols('X')] *= np.sqrt(scale)
        self.y[symbols('Y')] *= np.sqrt(scale)
    
    @property
    def X(self):
        return self.y[symbols('X')]
    @property
    def Y(self):
        return self.y[symbols('Y')]
    @property
    def W(self):
        return self.y[symbols('W')]
    @property
    def w(self):
        return self.y[symbols('w')]
    @property
    def Brouwer(self):
        return self.y[symbols('Brouwer')]
    @property
    def K(self):
        return self.y[symbols('K')]
    @property
    def deltalambda(self):
        return self.y[symbols('\Delta\lambda')]
    @property
    def lambda1(self):
        return self.y[symbols('lambda1')]
    @property
    def Phi(self):
        return (self.X**2 + self.Y**2)/2.
    @property
    def phi(self):
        return np.arctan2(self.Y, self.X)
    @property
    def Phiprime(self):
        p = self.params
        return -self.Brouwer*p['Acoeff']* p['timescale']/3.
